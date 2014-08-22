import csv
import random
from StringIO import StringIO

import transaction
from zope.testing.loggingsupport import InstalledHandler

from plone.app.testing import login

from tutorweb.content.tests.base import setRelations
from .base import IntegrationTestCase
from .base import MANAGER_ID, USER_A_ID, USER_B_ID, USER_C_ID


class StudentResultsViewTest(IntegrationTestCase):
    maxDiff = None

    def setUp(self):
        """Set up a class ready for testing"""
        portal = self.layer['portal']
        login(portal, MANAGER_ID)

        if 'classa' not in portal:
            portal.invokeFactory(
                type_name="tw_class",
                id="classa",
                title="Unittest ClassA",
                students=[USER_A_ID, USER_C_ID, USER_B_ID],
                lectures=[],
            )
        else:
            portal['classa'].lectures = []

        self.loghandlers = dict(
            sqlalchemy=InstalledHandler('sqlalchemy.engine'),
            sync=InstalledHandler('tutorweb.quizdb.browser.sync')
        )

    def logs(self, name='sqlalchemy'):
        return [x.getMessage() for x in self.loghandlers[name].records]

    def test_lecturesInClass(self):
        """lecturesInClass should match obj.lectures"""
        portal = self.layer['portal']
        login(portal, MANAGER_ID)

        # A class without lectures returns nothing
        self.assertEqual(self.getView().lecturesInClass(), [
        ])

        # Add some lectures
        setRelations(portal['classa'], 'lectures', [
            portal['dept1']['tut1']['lec2'],
            portal['dept1']['tut1']['lec1'],
        ])
        self.assertEqual(self.getView().lecturesInClass(), [
            {'id': 'dept1/tut1/lec2', 'url': 'http://nohost/plone/dept1/tut1/lec2'},
            {'id': 'dept1/tut1/lec1', 'url': 'http://nohost/plone/dept1/tut1/lec1'},
        ])

    def test_allStudentGrades(self):
        """Get contents of table"""
        portal = self.layer['portal']
        lec1 = portal['dept1']['tut1']['lec1']
        lec2 = portal['dept1']['tut1']['lec2']
        login(portal, MANAGER_ID)

        # No lectures, but get students in specified order
        self.assertEqual(self.getView().allStudentGrades(), [
            dict(username=USER_A_ID, grades=[]),
            dict(username=USER_C_ID, grades=[]),
            dict(username=USER_B_ID, grades=[]),
        ])

        # Add lectures, get blank value for each
        setRelations(portal['classa'], 'lectures', [lec2, lec1])
        self.assertEqual(self.getView().allStudentGrades(), [
            dict(username=USER_A_ID, grades=['-', '-']),
            dict(username=USER_C_ID, grades=['-', '-']),
            dict(username=USER_B_ID, grades=['-', '-']),
        ])

        # Arnold answers a question
        self.updateAnswerQueue(USER_A_ID, lec1, [0.1, 0.3])
        self.assertEqual(self.getView().allStudentGrades(), [
            dict(username=USER_A_ID, grades=['-', 0.3]),
            dict(username=USER_C_ID, grades=['-', '-']),
            dict(username=USER_B_ID, grades=['-', '-']),
        ])

        # More answers appear
        self.updateAnswerQueue(USER_A_ID, lec2, [0.4, 0.8])
        self.updateAnswerQueue(USER_B_ID, lec2, [0.2])
        self.assertEqual(self.getView().allStudentGrades(), [
            dict(username=USER_A_ID, grades=[0.8, 0.3]),
            dict(username=USER_C_ID, grades=['-', '-']),
            dict(username=USER_B_ID, grades=[0.2, '-']),
        ])

        # Overwrite old answers
        self.updateAnswerQueue(USER_A_ID, lec2, [0.4, 0.8, 1.0])
        self.assertEqual(self.getView().allStudentGrades(), [
            dict(username=USER_A_ID, grades=[1.0, 0.3]),
            dict(username=USER_C_ID, grades=['-', '-']),
            dict(username=USER_B_ID, grades=[0.2, '-']),
        ])

    def test_StudentSummaryTableView(self):
        """Cheat and re-use test infrastructure for allStudentGrades()"""
        portal = self.layer['portal']
        lec1 = portal['dept1']['tut1']['lec1']
        lec2 = portal['dept1']['tut1']['lec2']
        login(portal, MANAGER_ID)

        # Set a bunch of results, should appear in CSV
        setRelations(portal['classa'], 'lectures', [lec2, lec1])
        self.updateAnswerQueue(USER_A_ID, lec2, [0.4, 0.8])
        self.updateAnswerQueue(USER_B_ID, lec2, [0.2])
        self.updateAnswerQueue(USER_A_ID, lec2, [0.4, 0.8, 1.0])
        self.assertEqual(self.getCSV(), [
            {'Student': 'Arnold',   'dept1/tut1/lec1': '-', 'dept1/tut1/lec2': '1'},
            {'Student': 'Caroline', 'dept1/tut1/lec1': '-', 'dept1/tut1/lec2': '-'},
            {'Student': 'Betty',    'dept1/tut1/lec1': '-', 'dept1/tut1/lec2': '0.2'},
        ])

    def updateAnswerQueue(self, user, lecture, grades):
        """Log in as user, run the answer queue part of sync"""
        login(self.layer['portal'], user)
        syncView = lecture.restrictedTraverse('@@quizdb-sync')
        student = syncView.getCurrentStudent()
        if not hasattr(self, 'timestamp'):
            self.timestamp = 1377000000
        else:
            self.timestamp += 100

        # Get an allocation, write back an answer, updating the grade
        qns = syncView.getQuestionAllocation(student, [], {})[0]
        out = syncView.parseAnswerQueue(student, [dict(
            synced=False,
            uri=qns[0]['uri'],
            student_answer=0,
            correct=True,
            quiz_time=self.timestamp,
            answer_time=self.timestamp + 10,
            grade_after=grade,
        ) for grade in grades], {})
        login(self.layer['portal'], MANAGER_ID)
        transaction.commit()
        return out

    def getView(self):
        """Look up view for class"""
        c = self.layer['portal']['classa']
        return c.restrictedTraverse('student-results')

    def getCSV(self):
        """Look up view for class, return CSV as array of dicts"""
        c = self.layer['portal']['classa']
        csvString = c.restrictedTraverse('student-summary')()
        return [x for x in csv.DictReader(StringIO(csvString))]


class StudentTableViewTest(IntegrationTestCase):
    maxDiff = None

    def setUp(self):
        """Set up a class ready for testing"""
        portal = self.layer['portal']
        login(portal, MANAGER_ID)

        if 'classa' not in portal:
            portal.invokeFactory(
                type_name="tw_class",
                id="classa",
                title="Unittest ClassA",
                students=[USER_A_ID, USER_C_ID, USER_B_ID],
                lectures=[],
            )
        else:
            portal['classa'].lectures = []

        self.loghandlers = dict(
            sqlalchemy=InstalledHandler('sqlalchemy.engine'),
            sync=InstalledHandler('tutorweb.quizdb.browser.sync')
        )

    def logs(self, name='sqlalchemy'):
        return [x.getMessage() for x in self.loghandlers[name].records]

    def test_noAnswers(self):
        """Generating an empty CSV isn't a problem"""
        c = self.getCSV()
        self.assertEqual(c, [])

    def test_withAnswers(self):
        """Answers come back in correct order"""
        portal = self.layer['portal']
        lec1 = portal['dept1']['tut1']['lec1']
        lec2 = portal['dept1']['tut1']['lec2']
        login(portal, MANAGER_ID)
        setRelations(portal['classa'], 'lectures', [lec2, lec1])

        self.updateAnswerQueue(USER_B_ID, lec1, [0.4, 0.8])
        self.updateAnswerQueue(USER_A_ID, lec1, [0.3, 0.9])
        self.updateAnswerQueue(USER_B_ID, lec2, [0.41, 0.81])
        self.updateAnswerQueue(USER_A_ID, lec2, [0.31, 0.91])
        for grade in [0.59, 0.51, 0.58, 0.52, 0.57, 0.53, 0.56, 0.55, 0.54]:
            # Break up calls so we record a different time for each, enough
            # here that some won't have the same question assigned.
            self.updateAnswerQueue(USER_A_ID, lec1, [grade])
        c = self.getCSV()
        self.assertEqual([[x['Student'], x['Lecture'][-4:], x['Grade'], x['Time answered']] for x in c], [
            ['Arnold', 'lec1', '0.3', '2013-08-20 13:01:50'],
            ['Arnold', 'lec1', '0.9', '2013-08-20 13:01:50'],
            ['Arnold', 'lec1', '0.59', '2013-08-20 13:06:50'],
            ['Arnold', 'lec1', '0.51', '2013-08-20 13:08:30'],
            ['Arnold', 'lec1', '0.58', '2013-08-20 13:10:10'],
            ['Arnold', 'lec1', '0.52', '2013-08-20 13:11:50'],
            ['Arnold', 'lec1', '0.57', '2013-08-20 13:13:30'],
            ['Arnold', 'lec1', '0.53', '2013-08-20 13:15:10'],
            ['Arnold', 'lec1', '0.56', '2013-08-20 13:16:50'],
            ['Arnold', 'lec1', '0.55', '2013-08-20 13:18:30'],
            ['Arnold', 'lec1', '0.54', '2013-08-20 13:20:10'],
            ['Arnold', 'lec2', '0.31', '2013-08-20 13:05:10'],
            ['Arnold', 'lec2', '0.91', '2013-08-20 13:05:10'],
            ['Betty', 'lec1', '0.4', '2013-08-20 13:00:10'],
            ['Betty', 'lec1', '0.8', '2013-08-20 13:00:10'],
            ['Betty', 'lec2', '0.41', '2013-08-20 13:03:30'],
            ['Betty', 'lec2', '0.81', '2013-08-20 13:03:30'],
        ])

    def getCSV(self):
        """Look up view for class, return CSV as array of dicts"""
        c = self.layer['portal']['classa']
        csvString = c.restrictedTraverse('student-table')()
        return [x for x in csv.DictReader(StringIO(csvString))]

    def updateAnswerQueue(self, user, lecture, grades):
        """Log in as user, run the answer queue part of sync"""
        login(self.layer['portal'], user)
        syncView = lecture.restrictedTraverse('@@quizdb-sync')
        student = syncView.getCurrentStudent()
        if not hasattr(self, 'timestamp'):
            self.timestamp = 1377000000
        else:
            self.timestamp += 100

        # Get an allocation, write back an answer, updating the grade
        qns = syncView.getQuestionAllocation(student, [], {})[0]
        out = syncView.parseAnswerQueue(student, [dict(
            synced=False,
            uri=random.choice(qns)['uri'],
            student_answer=0,
            correct=True,
            quiz_time=self.timestamp,
            answer_time=self.timestamp + 10,
            grade_after=grade,
        ) for grade in grades], {})
        login(self.layer['portal'], MANAGER_ID)
        transaction.commit()
        return out
