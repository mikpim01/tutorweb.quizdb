import os
import tempfile
from unittest import TestCase
import json

from plone.app.testing import IntegrationTesting, FunctionalTesting
from zope.configuration import xmlconfig

# Nab test case setup from tutorweb.content
from tutorweb.content.tests.base import (
    USER_A_ID,
    USER_B_ID,
    USER_C_ID,
    MANAGER_ID,
)
from tutorweb.content.tests.base import TestFixture as ContentTestFixture
from tutorweb.content.tests.base import FunctionalTestCase as ContentFunctionalTestCase

class TestFixture(ContentTestFixture):
    def setUpZope(self, app, configurationContext):
        super(TestFixture, self).setUpZope(app, configurationContext)
        import tutorweb.quizdb
        xmlconfig.include(configurationContext, 'configure.zcml', tutorweb.quizdb)
        self.createTempDatabase(configurationContext)
        configurationContext.execute_actions()

    def tearDownZope(self, app):
        if self.dbFileName:
            os.unlink(self.dbFileName)

    def createTempDatabase(self, configurationContext):
        """Create database and update ZCML"""
        fileno, self.dbFileName = tempfile.mkstemp(suffix='.twquizdb.db')
        xmlconfig.string("""
          <configure xmlns="http://namespaces.zope.org/zope"
                     xmlns:db="http://namespaces.zope.org/db">
            <include package="z3c.saconfig" file="meta.zcml" />
            <db:engine name="tutorweb.quizdb" url="sqlite:///%s" />
            <db:session engine="tutorweb.quizdb" />
          </configure>
        """ % self.dbFileName, context=configurationContext)


FIXTURE = TestFixture()

TUTORWEB_QUIZDB_INTEGRATION_TESTING = IntegrationTesting(
    bases=(FIXTURE,),
    name="tutorweb.quizdb:Integration",
    )
TUTORWEB_QUIZDB_FUNCTIONAL_TESTING = FunctionalTesting(
    bases=(FIXTURE,),
    name="tutorweb.quizdb:Functional",
    )


class IntegrationTestCase(TestCase):
    layer = TUTORWEB_QUIZDB_INTEGRATION_TESTING


class FunctionalTestCase(ContentFunctionalTestCase):
    layer = TUTORWEB_QUIZDB_FUNCTIONAL_TESTING

    def getJson(self, path, body=None ,user=USER_A_ID, expectedStatus=200):
        """Call view, decode JSON results"""
        browser = self.getBrowser(None, user=user)
        browser.handleErrors = False
        browser.raiseHttpErrors = False
        if body:
            browser.post(path, json.dumps(body))
        else:
            browser.open(path)
        self.assertEqual(browser.headers['content-type'], 'application/json')
        self.assertEqual(
            browser.headers['Status'][0:3],
            str(expectedStatus),
            msg="Status %s didn't match %s: %s" % (
                browser.headers['Status'][0:3],
                str(expectedStatus),
                browser.contents,
            )
        )
        return json.loads(browser.contents)