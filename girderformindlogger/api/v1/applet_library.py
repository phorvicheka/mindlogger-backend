# -*- coding: utf-8 -*-
from ..rest import Resource
from ..describe import Description, autoDescribeRoute
from girderformindlogger.api import access
from girderformindlogger.models.applet_library import AppletLibrary as AppletLibraryModel
from girderformindlogger.constants import AccessType, SortDir, TokenScope,     \
    DEFINED_INFORMANTS, REPROLIB_CANONICAL, SPECIAL_SUBJECTS, USER_ROLES
from girderformindlogger.models.profile import Profile as ProfileModel
from girderformindlogger.models.applet_categories import AppletCategory
from girderformindlogger.models.applet import Applet as AppletModel
from girderformindlogger.models.user import User as UserModel
from girderformindlogger.models.applet_basket import AppletBasket
from girderformindlogger.utility import jsonld_expander
from pymongo import DESCENDING, ASCENDING
from bson.objectid import ObjectId


USER_ROLE_KEYS = USER_ROLES.keys()

class AppletLibrary(Resource):
    """API Endpoint for managing library data in the system."""

    def __init__(self):
        super(AppletLibrary, self).__init__()
        self.resourceName = 'library'
        self._model = AppletLibraryModel()

        self.route('GET', ('applets',), self.getApplets)
        self.route('GET', ('categories',), self.getCategories)
        self.route('GET', (':id', 'checkName',), self.checkAppletName)
        self.route('GET', ('applet', 'content'), self.getPublishedApplet)

        self.route('POST', ('categories',), self.addCategory)
        self.route('POST', ('basket', ), self.setBasket)
        self.route('GET', ('basket', ), self.getBasket)
        self.route('PUT', ('basket', 'selection'), self.updateBasket)
        self.route('DELETE', ('basket', 'applet'), self.deleteAppletFromBasket)

    @access.user(scope=TokenScope.DATA_OWN)
    @autoDescribeRoute(
        Description('Set Basket.')
        .notes(
            'This endpoint is used after user logs in applet library. ( items added to based on logged out state are sent for initialization. )'
        )
        .jsonParam(
            'basket',
            'a json object specifying initial basket data',
            paramType='form',
            required=True
        )
    )
    def setBasket(self, basket):
        user = self.getCurrentUser()

        AppletBasket().setSelection(user['_id'], basket)

    @access.user(scope=TokenScope.DATA_OWN)
    @autoDescribeRoute(
        Description('Set Basket.')
        .notes(
            'This endpoint is used for getting current basket for user'
        )
    )
    def getBasket(self):
        user = self.getCurrentUser()

        return AppletBasket().getBasket(user['_id'])

    @access.user(scope=TokenScope.DATA_OWN)
    @autoDescribeRoute(
        Description('Update applet/activity/item selection.')
        .notes(
            'This endpoint is used when user adds new item in the basket or update selection on applet.'
        )
        .param(
            'appletId',
            'id of applet that selection is updated',
            required=True
        )
        .jsonParam(
            'selection',
            'A JSON Object containing information about basket update.',
            paramType='form',
            required=True
        )
    )
    def updateBasket(self, appletId, selection):
        user = self.getCurrentUser()

        for activitySelection in selection:
            AppletBasket().updateSelection(
                user['_id'],
                ObjectId(appletId),
                ObjectId(activitySelection['activityId']),
                activitySelection.get('items', None)
            )

    @access.user(scope=TokenScope.DATA_OWN)
    @autoDescribeRoute(
        Description('Delete a selection from basket.')
        .notes(
            'This endpoint is used for deleting a selection (applet) from basket.'
        )
        .param(
            'appletId',
            'id of applet that selection is going to be removed.',
            required=True
        )
    )
    def deleteAppletFromBasket(self, appletId):
        user = self.getCurrentUser()

        AppletBasket().deleteSelection(user['_id'], ObjectId(appletId))
        return {
            'message': 'deleted'
        }

    @access.public
    @autoDescribeRoute(
        Description('Get Published Applets.')
        .notes(
            'Get applets published in the library.'
        )
    )
    def getApplets(self):
        libraryApplets = list(self._model.find({}, sort=[("name", ASCENDING)]))

        appletIds = []
        for libraryApplet in libraryApplets:
            appletIds.append(libraryApplet['appletId'])

        appletModel = AppletModel()

        applets = list(appletModel.find({
            '_id': {
                '$in': appletIds
            }
        }))

        appletMetaInfoById = {}
        for applet in applets:
            appletMetaInfoById[str(applet['_id'])] = appletModel.getAppletMeta(applet)

        result = []
        for libraryApplet in libraryApplets:
            result.append({
                'id': libraryApplet['_id'],
                'name': libraryApplet['name'],
                'accountId': libraryApplet['accountId'],
                'categoryId': libraryApplet['categoryId'],
                'subCategoryId': libraryApplet['subCategoryId'],
                'keywords': libraryApplet['keywords'],
                'description': appletMetaInfoById[str(libraryApplet['appletId'])].get('description', ''),
                'image': appletMetaInfoById[str(libraryApplet['appletId'])].get('image', '')
            })

        return result

    @access.public
    @autoDescribeRoute(
        Description('Get Content of an applet.')
        .notes(
            'Get Content of published applet.'
        )
        .param(
            'libraryId',
            description='ID of the applet in the library',
            required=True
        )
    )
    def getPublishedApplet(self, libraryId):
        libraryApplet = self._model.findOne({
            '_id': ObjectId(libraryId)
        })

        applet = AppletModel().findOne({
            '_id': libraryApplet['appletId']
        })

        formatted = jsonld_expander.formatLdObject(
            applet,
            'applet',
            None,
            refreshCache=False
        )

        formatted['accountId'] = libraryApplet['accountId']

        return formatted

    @access.public
    @autoDescribeRoute(
        Description('Get Applet Categories.')
        .notes(
            'Get categories/sub-categories for applets.'
        )
    )
    def getCategories(self):
        categories = list(AppletCategory().find({}, fields=['name', 'parentId']))
        return categories

    @access.user(scope=TokenScope.DATA_OWN)
    @autoDescribeRoute(
        Description('Check applet name in the Library.')
        .notes(
            'Check if there is an applet with same name already exists in the library. <br>'
        )
        .modelParam(
            'id',
            model=AppletModel,
            description='ID of the applet',
            destName='applet',
            level=AccessType.ADMIN
        )
        .param(
            'name',
            'name of applet',
            required=True
        )
        .errorResponse('Write access was denied for this applet.', 403)
    )
    def checkAppletName(self, applet, name):
        existing = self._model.findOne({
            'name': name,
            'appletId': {
                '$ne': applet['_id']
            }
        })

        if existing:
            return False

        return True

    @access.public
    @autoDescribeRoute(
        Description('Get Content of an applet.')
        .notes(
            'Get Content of published applet.'
        )
        .param(
            'name',
            'name of category',
            required=True
        )
        .param(
            'parentId',
            'parent category id',
            required=False,
            default=None
        )
    )
    def addCategory(self, name, parentId=None):
        return AppletCategory().addCategory(name, parentId)
