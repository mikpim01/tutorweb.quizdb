import logging
import os
import sys
import time

import transaction
from z3c.saconfig import Session
from zope.testing.loggingsupport import InstalledHandler

from plone.app.testing import login

from tutorweb.quizdb import ORMBase
from .base import FunctionalTestCase
from .base import USER_A_ID, USER_B_ID, MANAGER_ID


class SyncViewTest(FunctionalTestCase):
    maxDiff = None
    def setUp(self):
        self.loghandlers = dict(
            sqlalchemy=InstalledHandler('sqlalchemy.engine'),
            sync=InstalledHandler('tutorweb.quizdb.browser.sync')
        )

    def tearDown(self):
        """Drop all DB tables and recreate"""
        Session().execute("DROP TABLE allocation")
        Session().execute("DROP TABLE lecture")
        Session().execute("DROP TABLE question")
        Session().execute("DROP TABLE student")
        Session().execute("DROP TABLE answer")
        ORMBase.metadata.create_all(Session().bind)

    def logs(self, name='sqlalchemy'):
        return [x.getMessage() for x in self.loghandlers[name].records]

    def test_anonymous(self):
        """Anonymous users should get a 403 (not a redirect to login)"""
        out = self.getJson('http://nohost/plone/dept1/tut1/lec1/@@quizdb-sync', expectedStatus=403, user=None)
        self.assertEqual(out['error'], 'Unauthorized')

    def test_allocate(self):
        """Allocate some questions"""
        # Allocate lecture 1 to user A
        aAlloc = self.getJson('http://nohost/plone/dept1/tut1/lec1/@@quizdb-sync', user=USER_A_ID)
        self.assertEquals(aAlloc['title'], u'Unittest D1 T1 L1')
        self.assertEquals(aAlloc['uri'], u'http://nohost/plone/dept1/tut1/lec1/quizdb-sync')
        self.assertEquals(aAlloc['question_uri'], u'http://nohost/plone/dept1/tut1/lec1/quizdb-all-questions')
        self.assertEquals(aAlloc['user'], u'Arnold')
        self.assertEquals(len(aAlloc['questions']), 2)
        self.assertEquals(
            sorted([self.getJson(qn['uri'])['title'] for qn in aAlloc['questions']]),
            [u'Unittest D1 T1 L1 Q1', u'Unittest D1 T1 L1 Q2'],
        )

        # Allocate lecture 2 to user A, should get all-new questions.
        aAlloc2 = self.getJson('http://nohost/plone/dept1/tut1/lec2/@@quizdb-sync', user=USER_A_ID)
        self.assertEquals(aAlloc2['title'], u'Unittest D1 T1 L2')
        self.assertEquals(aAlloc2['uri'], u'http://nohost/plone/dept1/tut1/lec2/quizdb-sync')
        self.assertEquals(aAlloc2['question_uri'], u'http://nohost/plone/dept1/tut1/lec2/quizdb-all-questions')
        self.assertEquals(len(aAlloc2['questions']), 2)
        self.assertEquals(
            sorted([self.getJson(qn['uri'])['title'] for qn in aAlloc2['questions']]),
            [u'Unittest D1 T1 L2 Q1', u'Unittest D1 T1 L2 Q2'],
        )

        # User B gets a different allocation
        bAlloc = self.getJson('http://nohost/plone/dept1/tut1/lec1/@@quizdb-sync', user=USER_B_ID)
        self.assertEquals(bAlloc['title'], u'Unittest D1 T1 L1')
        self.assertEquals(bAlloc['uri'], u'http://nohost/plone/dept1/tut1/lec1/quizdb-sync')
        self.assertEquals(bAlloc['question_uri'], u'http://nohost/plone/dept1/tut1/lec1/quizdb-all-questions')
        self.assertEquals(bAlloc['user'], u'Betty')
        self.assertEquals(len(bAlloc['questions']), 2)
        self.assertTrue(aAlloc['questions'][0]['uri'] != bAlloc['questions'][0]['uri'])
        self.assertTrue(aAlloc['questions'][0]['uri'] != bAlloc['questions'][1]['uri'])
        self.assertTrue(aAlloc['questions'][1]['uri'] != bAlloc['questions'][0]['uri'])
        self.assertTrue(aAlloc['questions'][1]['uri'] != bAlloc['questions'][1]['uri'])

        # Still get the same allocations if we call again
        aAlloc1 = self.getJson('http://nohost/plone/dept1/tut1/lec1/@@quizdb-sync', user=USER_A_ID)
        bAlloc1 = self.getJson('http://nohost/plone/dept1/tut1/lec1/@@quizdb-sync', user=USER_B_ID)
        self.assertTrue(aAlloc['questions'][0]['uri'] == aAlloc1['questions'][0]['uri'])
        self.assertTrue(aAlloc['questions'][1]['uri'] == aAlloc1['questions'][1]['uri'])
        self.assertTrue(bAlloc['questions'][0]['uri'] == bAlloc1['questions'][0]['uri'])
        self.assertTrue(bAlloc['questions'][1]['uri'] == bAlloc1['questions'][1]['uri'])

    def test_adddelete(self):
        """Allocate some questions"""
        portal = self.layer['portal']

        # Start with 2 questions
        aAlloc = self.getJson('http://nohost/plone/dept1/tut1/lec1/@@quizdb-sync', user=USER_A_ID)
        self.assertEquals(
            sorted([self.getJson(qn['uri'])['title'] for qn in aAlloc['questions']]),
            [u'Unittest D1 T1 L1 Q1', u'Unittest D1 T1 L1 Q2'],
        )

        # Add a question3, appears in sync call
        login(portal, MANAGER_ID)
        portal['dept1']['tut1']['lec1'].invokeFactory(
            type_name="tw_latexquestion",
            id="qn3",
            title="Unittest D1 T1 L1 Q3",
        )
        transaction.commit()
        aAlloc = self.getJson('http://nohost/plone/dept1/tut1/lec1/@@quizdb-sync', user=USER_A_ID)
        self.assertEquals(
            sorted([self.getJson(qn['uri'])['title'] for qn in aAlloc['questions']]),
            [u'Unittest D1 T1 L1 Q1', u'Unittest D1 T1 L1 Q2', u'Unittest D1 T1 L1 Q3'],
        )

        # Delete question3, doesn't appear in sync
        browser = self.getBrowser('http://nohost/plone/dept1/tut1/lec1/qn3/delete_confirmation', user=MANAGER_ID)
        browser.getControl('Delete').click()
        aAlloc = self.getJson('http://nohost/plone/dept1/tut1/lec1/@@quizdb-sync', user=USER_A_ID)
        self.assertEquals(
            sorted([self.getJson(qn['uri'])['title'] for qn in aAlloc['questions']]),
            [u'Unittest D1 T1 L1 Q1', u'Unittest D1 T1 L1 Q2'],
        )
        aAlloc = self.getJson('http://nohost/plone/dept1/tut1/lec1/@@quizdb-sync', user=USER_A_ID)
        self.assertEquals(
            sorted([self.getJson(qn['uri'])['title'] for qn in aAlloc['questions']]),
            [u'Unittest D1 T1 L1 Q1', u'Unittest D1 T1 L1 Q2'],
        )

    def test_settings(self):
        """Make sure settings are inherited from tutorial"""
        portal = self.layer['portal']

        portal['dept1']['tut1'].settings = dict(
            hist_sel='0.8',
            value_a='x',
            value_b='x',
        )
        portal['dept1']['tut1']['lec1'].settings = dict(
            value_b='y',
            value_c='y',
        )
        transaction.commit()
        aAlloc = self.getJson('http://nohost/plone/dept1/tut1/lec1/@@quizdb-sync', user=USER_A_ID)
        self.assertEqual(aAlloc['settings'], dict(
            hist_sel='0.8',
            value_a='x',
            value_b='y',
            value_c='y',
        ))

        # Still works if lecture is None
        portal['dept1']['tut1'].settings = dict(
            hist_sel='0.8',
            value_a='x',
            value_b='x',
        )
        portal['dept1']['tut1']['lec1'].settings = None
        transaction.commit()
        aAlloc = self.getJson('http://nohost/plone/dept1/tut1/lec1/@@quizdb-sync', user=USER_A_ID)
        self.assertEqual(aAlloc['settings'], dict(
            hist_sel='0.8',
            value_a='x',
            value_b='x',
        ))

        # Still works if tutorial is none
        portal['dept1']['tut1'].settings = None
        portal['dept1']['tut1']['lec1'].settings = dict(
            value_b='y',
            value_c='y',
        )
        transaction.commit()
        aAlloc = self.getJson('http://nohost/plone/dept1/tut1/lec1/@@quizdb-sync', user=USER_A_ID)
        self.assertEqual(aAlloc['settings'], dict(
            value_b='y',
            value_c='y',
        ))

    def test_answerQueuePersistent(self):
        """Make sure answerQueue gets logged and is returned"""
        # Allocate to user A
        aAlloc = self.getJson('http://nohost/plone/dept1/tut1/lec1/@@quizdb-sync', user=USER_A_ID)
        self.assertEquals(
            sorted([self.getJson(qn['uri'])['title'] for qn in aAlloc['questions']]),
            [u'Unittest D1 T1 L1 Q1', u'Unittest D1 T1 L1 Q2'],
        )

        # Write some answers back
        aAlloc = self.getJson('http://nohost/plone/dept1/tut1/lec1/@@quizdb-sync', user=USER_A_ID, body=dict(
            user='Arnold',
            answerQueue=[
                dict(
                    synced=False,
                    uri=aAlloc['questions'][0]['uri'],
                    student_answer=0,
                    correct='wibble',
                    quiz_time=1377000000,
                    answer_time=1377000010,
                    grade_after=0.1,
                ),
                dict(
                    synced=False,
                    uri=aAlloc['questions'][1]['uri'],
                    student_answer=99,
                    correct=False,
                    quiz_time=1377000020,
                    answer_time=1377000030,
                    grade_after=0.2,
                ),
                dict(
                    synced=False,
                    uri=aAlloc['questions'][1]['uri'],
                    student_answer=2,
                    correct=True,
                    quiz_time=1377000020,
                    answer_time=1377000030,
                    grade_after=0.3,
                ),
            ],
        ))

        # Noticed that middle item wasn't correct
        self.assertEqual(self.logs('sync'), ['Student answer 99 out of range'])
        # Returned answerQueue without dodgy answer
        self.assertEqual(aAlloc['answerQueue'], [
                {
                    u'synced': True,
                    u'student_answer': 0,
                    u'correct': False,
                    u'quiz_time': 1377000000,
                    u'answer_time': 1377000010,
                    u'grade_after': 0.1,
                },
                {
                    u'synced': True,
                    u'student_answer': 2,
                    u'correct': True,
                    u'quiz_time': 1377000020,
                    u'answer_time': 1377000030,
                    u'grade_after': 0.3,
                    u'lec_answered': 2,
                    u'lec_correct': 1,
                },
        ])

        # Fetching again returns the same queue
        aAlloc = self.getJson('http://nohost/plone/dept1/tut1/lec1/@@quizdb-sync', user=USER_A_ID)
        self.assertEqual(aAlloc['answerQueue'], [
                {
                    u'synced': True,
                    u'student_answer': 0,
                    u'correct': False,
                    u'quiz_time': 1377000000,
                    u'answer_time': 1377000010,
                    u'grade_after': 0.1,
                },
                {
                    u'synced': True,
                    u'student_answer': 2,
                    u'correct': True,
                    u'quiz_time': 1377000020,
                    u'answer_time': 1377000030,
                    u'grade_after': 0.3,
                    u'lec_answered': 2,
                    u'lec_correct': 1,
                },
        ])

        # Writing a third time updates totals
        aAlloc = self.getJson('http://nohost/plone/dept1/tut1/lec1/@@quizdb-sync', user=USER_A_ID, body=dict(
            user='Arnold',
            answerQueue=[
                dict(
                    synced=False,
                    uri=aAlloc['questions'][1]['uri'],
                    student_answer=2,
                    correct=False,  # NB: Sending back false even though question is really true
                    quiz_time=1377000040,
                    answer_time=1377000050,
                    grade_after=0.1,
                ),
            ]
        ))
        self.assertEqual(len(aAlloc['answerQueue']), 3)
        self.assertEqual(aAlloc['answerQueue'][-1]['answer_time'], 1377000050)
        self.assertEqual(aAlloc['answerQueue'][-1]['lec_answered'], 3)
        self.assertEqual(aAlloc['answerQueue'][-1]['lec_correct'], 2)
        self.assertEqual(aAlloc['answerQueue'][-1]['correct'], True)

    def test_answerQueueIsolation(self):
        """Make sure answerQueues for students and lectures are separate"""
        # Allocate to user A
        aAlloc = self.getJson('http://nohost/plone/dept1/tut1/lec1/@@quizdb-sync', user=USER_A_ID)
        self.assertEquals(
            sorted([self.getJson(qn['uri'])['title'] for qn in aAlloc['questions']]),
            [u'Unittest D1 T1 L1 Q1', u'Unittest D1 T1 L1 Q2'],
        )

        # Write some answers back
        aAlloc = self.getJson('http://nohost/plone/dept1/tut1/lec1/@@quizdb-sync', user=USER_A_ID, body=dict(
            answerQueue=[
                dict(
                    synced=False,
                    uri=aAlloc['questions'][0]['uri'],
                    student_answer=0,
                    correct='wibble',
                    quiz_time=1377000000,
                    answer_time=1377000010,
                    grade_after=0.1,
                ),
                dict(
                    synced=False,
                    uri=aAlloc['questions'][1]['uri'],
                    student_answer=2,
                    correct=True,
                    quiz_time=1377000020,
                    answer_time=1377000030,
                    grade_after=0.3,
                ),
            ],
        ))

        # Get user B, has no answers yet.
        bAlloc = self.getJson('http://nohost/plone/dept1/tut1/lec1/@@quizdb-sync', user=USER_B_ID)
        self.assertEquals(bAlloc['answerQueue'], [
        ])

        # Write some answers back, can only write back B's allocation
        bAlloc = self.getJson('http://nohost/plone/dept1/tut1/lec1/@@quizdb-sync', user=USER_B_ID, body=dict(
            user='Betty',
            answerQueue=[
                dict(
                    synced=False,
                    uri=aAlloc['questions'][0]['uri'],
                    student_answer=0,
                    correct=True,
                    quiz_time=1377000040,
                    answer_time=1377000050,
                    grade_after=0.3,
                ),
                dict(
                    synced=False,
                    uri=bAlloc['questions'][0]['uri'],
                    student_answer=0,
                    correct=True,
                    quiz_time=1377000041,
                    answer_time=1377000051,
                    grade_after=0.3,
                ),
            ],
        ))
        self.assertEquals(len(bAlloc['answerQueue']), 1)
        self.assertEquals(bAlloc['answerQueue'][0]['quiz_time'], 1377000041)
        self.assertTrue((
            u'No record of allocation %s for student Betty'
            % aAlloc['questions'][0]['uri'].replace('http://nohost/plone/quizdb-get-question/', '')
        ) in self.logs('sync'))

        # A doesn't see B's answer
        aAlloc = self.getJson('http://nohost/plone/dept1/tut1/lec1/@@quizdb-sync', user=USER_A_ID)
        self.assertEqual(aAlloc['answerQueue'], [
                {
                    u'synced': True,
                    u'student_answer': 0,
                    u'correct': False,
                    u'quiz_time': 1377000000,
                    u'answer_time': 1377000010,
                    u'grade_after': 0.1,
                },
                {
                    u'synced': True,
                    u'student_answer': 2,
                    u'correct': True,
                    u'quiz_time': 1377000020,
                    u'answer_time': 1377000030,
                    u'grade_after': 0.3,
                    u'lec_answered': 2,
                    u'lec_correct': 1,
                },
        ])

        # A can't write back answers for B
        bAlloc = self.getJson('http://nohost/plone/dept1/tut1/lec1/@@quizdb-sync', user=USER_A_ID, body=dict(
            user='Betty',
            answerQueue=[
                dict(
                    synced=False,
                    uri=aAlloc['questions'][0]['uri'],
                    student_answer=2,
                    correct=True,
                    quiz_time=1377000060,
                    answer_time=1377000070,
                    grade_after=0.3,
                ),
            ],
        ), expectedStatus=403)
        bAlloc = self.getJson('http://nohost/plone/dept1/tut1/lec1/@@quizdb-sync', user=USER_B_ID)
        self.assertEquals(len(bAlloc['answerQueue']), 1)
        self.assertEquals(bAlloc['answerQueue'][0]['quiz_time'], 1377000041)
