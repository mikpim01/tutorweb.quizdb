import datetime
import json
import logging
import random
import pytz

from sqlalchemy.orm import aliased
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql.expression import func

from z3c.saconfig import Session

from tutorweb.content.schema import IQuestion
from tutorweb.quizdb import db

# logging.getLogger('sqlalchemy.engine').setLevel(logging.DEBUG)
logger = logging.getLogger(__package__)

DEFAULT_QUESTION_CAP = 100  # Maximum number of questions to assign to user


def toUTCDateTime(t):
    # Convert Zope DateTime into UTC datetime object
    # NB: MySQL cannae store less than second resolution
    return t.asdatetime().astimezone(pytz.utc).replace(microsecond=0, tzinfo=None)


def syncPloneQuestions(dbLec, lectureObj):
    """Ensure database has same questions as Plone"""
    # Get all plone questions, turn it into a dict by path
    ploneQns = {}
    if getattr(lectureObj, 'isAlias', False):
        lectureObj = lectureObj._target
    listing = lectureObj.portal_catalog.unrestrictedSearchResults(
        path={'query': '/'.join(lectureObj.getPhysicalPath()), 'depth': 1},
        object_provides=IQuestion.__identifier__
    )
    for l in listing:
        obj = l.getObject()
        data = obj.unrestrictedTraverse('@@data')
        # objPath is the canonical location of the question
        objPath = '/'.join(obj._target.getPhysicalPath()) \
                  if getattr(obj, 'isAlias', False) else l.getPath()

        if l['portal_type'] == 'tw_questionpack':
            # Expand question pack out into individual questions
            for (id, qn) in data.allQuestionsDict().iteritems():
                ploneQns['%s?question_id=%s' % (objPath, id)] = dict(
                    qnType='tw_latexquestion',
                    lastUpdate=toUTCDateTime(l['modified']),
                    correctChoices=[i for (i, x) in enumerate(qn['choices']) if x['correct']],
                    timesAnswered=qn.get('timesanswered', 0),
                    timesCorrect=qn.get('timescorrect', 0),
                )
        else:
            # Add individual question
            try:
                allChoices = data.allChoices()
            except AttributeError:
                # Template questions don't have correct answers
                allChoices = []
            correctChoices = [i for i, a in enumerate(allChoices) if a['correct']]

            ploneQns[objPath] = dict(
                qnType=l['portal_type'],
                lastUpdate=toUTCDateTime(l['modified']),
                correctChoices=correctChoices,
                timesAnswered=getattr(obj, 'timesanswered', 0),
                timesCorrect=getattr(obj, 'timescorrect', 0),
            )

    # Get all questions currently in the database
    for dbQn in (Session.query(db.Question).filter(db.Question.lectures.contains(dbLec))):
        qn = ploneQns.get(dbQn.plonePath, None)
        if qn is not None:
            # Question still there (or returned), update
            dbQn.active = True
            dbQn.correctChoices = json.dumps(qn['correctChoices'])
            dbQn.lastUpdate = qn['lastUpdate']
            # Dont add this question later
            del ploneQns[dbQn.plonePath]
        elif dbQn.active and getattr(obj, 'isAlias', False):
            # Remove symlink question from lecture
            dbQn.lectures = [l for l in dbQn.lectures if l != dbLec]
            dbQn.active = len(dbQn.lectures) > 0
            dbQn.lastUpdate = datetime.datetime.utcnow()
        elif dbQn.active:
            # Remove question from all lectures and mark as inactive
            dbQn.lectures = []
            dbQn.active = False
            dbQn.lastUpdate = datetime.datetime.utcnow()
        else:
            # No question & already removed from DB
            pass

    # Insert any remaining questions
    for (path, qn) in ploneQns.iteritems():
        try:
            # If question already exists, add it to this lecture.
            dbQn = Session.query(db.Question).filter(db.Question.plonePath == path).one()
            dbQn.lectures.append(dbLec)
            dbQn.active = True
        except NoResultFound:
            Session.add(db.Question(
                plonePath=path,
                qnType=qn['qnType'],
                lastUpdate=qn['lastUpdate'],
                correctChoices=json.dumps(qn['correctChoices']),
                timesAnswered=qn['timesAnswered'],
                timesCorrect=qn['timesCorrect'],
                lectures=[dbLec],
            ))

    Session.flush()


def getQuestionAllocation(dbLec, student, questionRoot, settings, targetDifficulty=None, reAllocQuestions=False):
    def questionUrl(publicId):
        return questionRoot + '/quizdb-get-question/' + publicId

    # Get all existing allocations from the DB and their questions
    allocsByType = dict(
        tw_latexquestion=[],
        tw_questiontemplate=[],
        # NB: Need to add rows for each distinct question type, otherwise won't try and assign them
    )
    for (dbAlloc, dbQn) in (Session.query(db.Allocation, db.Question)
            .join(db.Question)
            .filter(db.Allocation.studentId == student.studentId)
            .filter(db.Allocation.active == True)
            .filter(db.Allocation.lectureId == dbLec.lectureId)):
        if not(dbQn.active) or (dbAlloc.allocationTime < dbQn.lastUpdate):
            # Question has been removed or is stale
            dbAlloc.active = False
        else:
            # Still around, so save it
            allocsByType[dbQn.qnType].append(dict(alloc=dbAlloc, question=dbQn))

    # Each question type should have at most question_cap questions
    for (qnType, allocs) in allocsByType.items():
        questionCap = int(settings.get('question_cap', DEFAULT_QUESTION_CAP))

        # If there's too many allocs, throw some away
        for i in sorted(random.sample(xrange(len(allocs)), max(len(allocs) - questionCap, 0)), reverse=True):
            allocs[i]['alloc'].active = False
            del allocs[i]

        # If there's questions to spare, and requested to do so, reallocate questions
        if len(allocs) == questionCap and reAllocQuestions:
            if targetDifficulty is None:
                raise ValueError("Must have a target difficulty to know what to remove")

            # Make ranking how likely questions are, based on targetDifficulty
            suitability = []
            for a in allocs:
                if a['question'].timesAnswered == 0:
                    # New questions should be added regardless
                    suitability.append(1)
                else:
                    suitability.append(1 - abs(targetDifficulty - float(a['question'].timesCorrect) / a['question'].timesAnswered))
            ranking = sorted(range(len(allocs)), key=lambda k: suitability[k])

            # Remove the least likely tenth
            for i in sorted(ranking[0:len(allocs) / 10 + 1], reverse=True):
                allocs[i]['alloc'].active = False
                del allocs[i]

        # Assign required questions randomly
        if len(allocs) < questionCap:
            if targetDifficulty is None:
                targetExp = None
            else:
                targetExp = func.abs(round(targetDifficulty * 50) - func.round((50.0 * db.Question.timesCorrect) / db.Question.timesAnswered))
            for dbQn in (Session.query(db.Question)
                    .filter(db.Question.lectures.contains(dbLec))
                    .filter(~db.Question.questionId.in_([a['alloc'].questionId for a in allocs]))
                    .filter(db.Question.qnType == qnType)
                    .filter(db.Question.active == True)
                    .order_by(targetExp)
                    .order_by(func.random())
                    .limit(max(questionCap - len(allocs), 0))):
                dbAlloc = db.Allocation(
                    studentId=student.studentId,
                    questionId=dbQn.questionId,
                    lectureId=dbLec.lectureId,
                    allocationTime=datetime.datetime.utcnow(),
                )
                Session.add(dbAlloc)
                allocs.append(dict(alloc=dbAlloc, question=dbQn))

    Session.flush()

    # Return all active questions
    return [dict(
        _type="template" if a['question'].qnType == 'tw_questiontemplate' else None,
        uri=questionUrl(a['alloc'].publicId),
        chosen=a['question'].timesAnswered,
        correct=a['question'].timesCorrect,
        online_only = (a['question'].qnType == 'tw_questiontemplate'),
    ) for allocs in allocsByType.values() for a in allocs]
