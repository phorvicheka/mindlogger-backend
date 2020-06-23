# -*- coding: utf-8 -*-
import base64
import cherrypy
import datetime
import itertools

from ..describe import Description, autoDescribeRoute
from girderformindlogger.api import access
from girderformindlogger.api.rest import Resource, filtermodel, setCurrentUser
from girderformindlogger.constants import AccessType, SortDir, TokenScope,     \
    USER_ROLES
from girderformindlogger.exceptions import RestException, AccessException
from girderformindlogger.models.applet import Applet as AppletModel
from girderformindlogger.models.collection import Collection as CollectionModel
from girderformindlogger.models.folder import Folder as FolderModel
from girderformindlogger.models.group import Group as GroupModel
from girderformindlogger.models.ID_code import IDCode
from girderformindlogger.models.profile import Profile as ProfileModel
from girderformindlogger.models.setting import Setting
from girderformindlogger.models.token import Token
from girderformindlogger.models.user import User as UserModel
from girderformindlogger.models.account_profile import AccountProfile
from girderformindlogger.settings import SettingKey
from girderformindlogger.utility import jsonld_expander, mail_utils
from sys import exc_info


class User(Resource):
    """API Endpoint for users in the system."""

    def __init__(self):
        super(User, self).__init__()
        self.resourceName = 'user'
        self._model = UserModel()

        self.route('DELETE', ('authentication',), self.logout)
        self.route('DELETE', (':id',), self.deleteUser)
        self.route('GET', (), self.find)
        self.route('GET', ('me',), self.getMe)
        self.route('GET', ('authentication',), self.login)
        self.route('PUT', ('applet', ':id', 'schedule'), self.setSchedule)
        self.route(
            'PUT',
            (':uid', 'applet', ':aid', 'schedule'),
            self.setOtherSchedule
        )
        self.route('GET', (':id',), self.getUserByID)
        self.route('GET', (':id', 'access'), self.getUserAccess)
        self.route('PUT', (':id', 'access'), self.updateUserAccess)
        self.route('GET', (':id', 'applets'), self.getUserApplets)
        self.route('PUT', (':id', 'code'), self.updateIDCode)
        self.route('DELETE', (':id', 'code'), self.removeIDCode)
        self.route('GET', ('applets',), self.getOwnApplets)
        self.route('GET', ('accounts',), self.getAccounts)
        self.route('PUT', ('switchAccount', ), self.switchAccount)
        self.route('GET', (':id', 'details'), self.getUserDetails)
        self.route('GET', ('invites',), self.getGroupInvites)
        self.route('PUT', (':id', 'knows'), self.setUserRelationship)
        self.route('GET', ('details',), self.getUsersDetails)
        self.route('POST', (), self.createUser)
        self.route('PUT', (':id',), self.updateUser)
        self.route('PUT', ('password',), self.changePassword)
        self.route('PUT', ('username',), self.changeUserName)
        self.route('PUT', ('accountName',), self.changeAccountName)

        self.route('PUT', (':id', 'password'), self.changeUserPassword)
        self.route('GET', ('password', 'temporary', ':id'),
                   self.checkTemporaryPassword)
        self.route('PUT', ('password', 'temporary'),
                   self.generateTemporaryPassword)
        self.route('POST', (':id', 'otp'), self.initializeOtp)
        self.route('PUT', (':id', 'otp'), self.finalizeOtp)
        self.route('DELETE', (':id', 'otp'), self.removeOtp)
        self.route('PUT', ('profile',), self.updateProfile)
        self.route('PUT', (':id', 'verification'), self.verifyEmail)
        self.route('POST', ('verification',), self.sendVerificationEmail)


    @access.user
    @autoDescribeRoute(
        Description('Get all pending invites for the logged-in user.')
        .deprecated()
    )
    def getGroupInvites(self):
        from girderformindlogger.utility.jsonld_expander import loadCache

        pending = self.getCurrentUser().get("groupInvites")
        output = []
        userfields = [
            'firstName',
            '_id',
            'email',
            'gravatar_baseUrl',
            'login'
        ]
        for p in pending:
            groupId = p.get('groupId')
            applets = list(AppletModel().find(
                query={
                    "roles.user.groups.id": groupId
                },
                fields=[
                    'cached',
                    'roles'
                ]
            ))
            for applet in applets:
                for role in ['manager', 'reviewer']:
                    applet[''.join([role, 's'])] = [{
                        (
                            'image' if userKey=='gravatar_baseUrl' else userKey
                        ): user.get(
                            userKey
                        ) for userKey in user.keys()
                    } for user in list(UserModel().find(
                            query={
                                "groups": {
                                    "$in": [
                                        group.get('id') for group in applet.get(
                                            'roles',
                                            {}
                                        ).get(role, {}).get('groups', [])
                                    ]
                                }
                            },
                            fields=userfields
                        ))
                    ]

            for applet in applets:
                applet['loadedCache'] = loadCache(applet['cached'])

            output.append({
                '_id': groupId,
                'applets': [{
                    'name': applet.get('loadedCache', {}).get('applet', {}).get(
                        'skos:prefLabel',
                        ''
                    ),
                    'image': applet.get('loadedCache', {}).get('applet', {}).get(
                        'schema:image',
                        ''
                    ),
                    'description': applet.get('loadedCache', {}).get('applet', {
                    }).get(
                        'schema:description',
                        ''
                    ),
                    'managers': applet.get('managers'),
                    'reviewers': applet.get('reviewers')
                } for applet in applets]
            })
        return(output)

    @access.user
    @filtermodel(model=UserModel)
    @autoDescribeRoute(
        Description('List or search for users.')
        .responseClass('User', array=True)
        .param('text', 'Pass this to perform a full text search for items.', required=False)
        .pagingParams(defaultSort='firstName')
        .deprecated()
    )
    def find(self, text, limit, offset, sort):
        return list(self._model.search(
            text=text, user=self.getCurrentUser(), offset=offset, limit=limit, sort=sort))

    @access.public(scope=TokenScope.USER_INFO_READ)
    @autoDescribeRoute(
        Description('Get a user by ID.')
        .notes(
            'This endpoint is used to get user data (firstName, lastName) from id'
        )
        .param('id', 'Profile ID or ID code', required=True)
        .errorResponse('ID was invalid.')
        .errorResponse('You do not have permission to see this user.', 403)
    )
    def getUserByID(self, id):
        from bson.objectid import ObjectId
        user = self.getCurrentUser()
        return(ProfileModel().getProfile(id, user))

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description('Set or update your own custom schedule information for an applet.')
        .notes(
            'This endpoint is used when users want to set their own custom schedule. <br>'
            'we are not using this functionality at the moment.'
        )
        .modelParam(
            'id',
            model=AppletModel,
            level=AccessType.READ,
            destName='applet'
        )
        .jsonParam(
            'schedule',
            'A JSON object containing schedule information for an activity',
            paramType='form',
            required=False
        )
        .errorResponse('Invalid applet ID.')
        .errorResponse('Read access was denied for this applet.', 403)
    )
    def setSchedule(self, applet, schedule, **kwargs):
        import threading

        thisUser = self.getCurrentUser()
        if not AppletModel()._hasRole(applet['_id'], thisUser, 'user'):
            raise AccessException(
                "You aren't a user of this applet."
            )
        profile = ProfileModel().findOne(
            {
                'appletId': applet['_id'],
                'userId': thisUser['_id'],
                'profile': True
            }
        )
        if not profile:
            raise AccessException(
                "You aren't a user of this applet."
            )
        ud = profile["userDefined"] if "userDefined" in profile else {}
        ud["schedule"] = schedule
        profile["userDefined"] = ud
        ProfileModel().save(profile, validate=False)

        return(profile["userDefined"])

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description('Set or update custom schedule information for a user of an applet you manage or coordinate.')
        .notes(
            'This endpoint designed for coordinators/managers to update individualized schedule. <br>'
            'But we are not using this endpoint at the moment. <br>'
            'Use PUT^applet/[id]/schedule instead of this.'
        )
        .modelParam(
            'uid',
            model=ProfileModel,
            force=True,
            destName='profile',
            description='The ID of the user\'s profile for this applet.'
        )
        .modelParam(
            'aid',
            model=AppletModel,
            level=AccessType.READ,
            destName='applet',
            description="The ID of the applet."
        )
        .jsonParam(
            'schedule',
            'A JSON object containing schedule information for an activity',
            paramType='form',
            required=False
        )
        .errorResponse('Invalid ID.')
        .errorResponse('Read access was denied.', 403)
        .deprecated()
    )
    def setOtherSchedule(self, profile, applet, schedule, **kwargs):
        import threading

        thisUser = self.getCurrentUser()
        if not AppletModel().isCoordinator(applet['_id'], thisUser):
            raise AccessException(
                "You aren't a coordinator or manager of this applet."
            )
        if profile["appletId"] not in [applet['_id'], str(applet['_id'])]:
            raise AccessException(
                "That profile is not a user of this applet."
            )
        ud = profile[
            "coordinatorDefined"
        ] if "coordinatorDefined" in profile else {}
        ud["schedule"] = schedule
        profile["coordinatorDefined"] = ud
        ProfileModel().save(profile, validate=False)

        return(profile["coordinatorDefined"])

    @access.public(scope=TokenScope.USER_INFO_READ)
    @autoDescribeRoute(
        Description('Add a relationship between users.')
        .param(
            'id',
            'ID or ID code of user to add relationship to',
            required=True
        )
        .param('rel', 'Relationship to add', required=True)
        .param('otherId', 'ID or ID code of related individual.', required=True)
        .param(
            'otherName',
            'Name to display for related individual',
            required=True
        )
        .errorResponse('ID was invalid.')
        .errorResponse('You do not have permission to see this user.', 403)
    )
    def setUserRelationship(self, id, rel, otherId, otherName):
        from girderformindlogger.models.invitation import Invitation
        from girderformindlogger.utility.jsonld_expander import                \
            inferRelationships, oidIffHex

        user = self.getCurrentUser()
        grammaticalSubject = ProfileModel().getProfile(id, user)
        gsp = ProfileModel().load(
            grammaticalSubject['_id'],
            force=True
        )
        grammaticalSubject = Invitation().load(
            grammaticalSubject['_id'],
            force=True
        ) if gsp is None else gsp
        print(grammaticalSubject)
        if grammaticalSubject is None or not AppletModel().isCoordinator(
            grammaticalSubject['appletId'], user
        ):
            raise AccessException(
                'You do not have permission to update this user.'
            )

        appletId = grammaticalSubject['appletId']
        grammaticalObject = ProfileModel().getSubjectProfile(
            otherId,
            otherName,
            user
        )
        if grammaticalObject is None:
            grammaticalObject = ProfileModel().getProfile(
                ProfileModel().createPassiveProfile(
                    appletId,
                    otherId,
                    otherName,
                    user
                )['_id'],
                grammaticalSubject
            )
        if 'schema:knows' in grammaticalSubject:
            if rel in grammaticalSubject['schema:knows'] and grammaticalObject[
                '_id'
            ] not in grammaticalSubject['schema:knows'][rel]:
                grammaticalSubject['schema:knows'][rel].append(
                    grammaticalObject['_id']
                )
            else:
                grammaticalSubject['schema:knows'][rel] = [
                    grammaticalObject['_id']
                ]
        else:
            grammaticalSubject['schema:knows'] = {
                rel: [grammaticalObject['_id']]
            }
        ProfileModel().save(grammaticalSubject, validate=False)
        inferRelationships(grammaticalSubject)
        return(ProfileModel().getProfile(id, user))


    @access.public(scope=TokenScope.USER_INFO_READ)
    @autoDescribeRoute(
        Description('Add a new ID Code to a user.')
        .param('id', 'Profile ID', required=True, paramType='path')
        .param('code', 'ID code to add to profile', required=True)
        .errorResponse('ID was invalid.')
        .errorResponse('You do not have permission to see this user.', 403)
    )
    def updateIDCode(self, id, code):
        from bson.objectid import ObjectId
        user = self.getCurrentUser()
        try:
            p = ProfileModel().findOne({'_id': ObjectId(id)})
        except:
            p = None
        if p is None or not AppletModel().isCoordinator(p['appletId'], user):
            raise AccessException(
                'You do not have permission to update this user\'s ID code.'
            )
        else:
            IDCode().createIdCode(p, code)
        return(
            ProfileModel().profileAsUser(
                ProfileModel().load(p['_id'], force=True),
                user
            )
        )

    @access.public(scope=TokenScope.USER_INFO_READ)
    @autoDescribeRoute(
        Description('Remove an ID Code from a user.')
        .param('id', 'Profile ID', required=True, paramType='path')
        .param(
            'code',
            'ID code to remove from profile. If the ID code to remove is the '
            'only ID code for that profile, a new one will be auto-generated.',
            required=True
        )
        .errorResponse('ID was invalid.')
        .errorResponse('You do not have permission to see this user.', 403)
    )
    def removeIDCode(self, id, code):
        from bson.objectid import ObjectId
        user = self.getCurrentUser()
        try:
            p = ProfileModel().findOne({'_id': ObjectId(id)})
        except:
            p = None
        if p is None or not AppletModel().isCoordinator(p['appletId'], user):
            raise AccessException(
                'You do not have permission to update this user\'s ID code.'
            )
        else:
            IDCode().removeCode(p['_id'], code)
        return(
            ProfileModel().profileAsUser(
                ProfileModel().load(p['_id'], force=True),
                user
            )
        )

    @access.user(scope=TokenScope.USER_INFO_READ)
    @autoDescribeRoute(
        Description('Get the access control list for a user.')
        .responseClass('User')
        .modelParam('id', model=UserModel, level=AccessType.READ)
        .errorResponse('ID was invalid.')
        .errorResponse('You do not have permission to see this user.', 403)
        .deprecated()
    )
    def getUserAccess(self, user):
        return self._model.getFullAccessList(user)

    @access.user(scope=TokenScope.DATA_OWN)
    @filtermodel(model=UserModel, addFields={'access'})
    @autoDescribeRoute(
        Description('Update the access control list for a user.')
        .modelParam('id', model=UserModel, level=AccessType.WRITE)
        .jsonParam(
            'access',
            'The JSON-encoded access control list.',
            requireObject=True
        )
        .errorResponse('ID was invalid.')
        .errorResponse('Admin access was denied for the user.', 403)
        .deprecated()
    )
    def updateUserAccess(self, user, access):
        return self._model.setAccessList(
            user,
            access,
            save=True
        )

    @access.public(scope=TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description('Get all applets for a user by that user\'s ID and role.')
        .modelParam('id', model=UserModel, level=AccessType.READ)
        .param(
            'role',
            'One of ' + str(USER_ROLES.keys()),
            required=False,
            default='user'
        )
        .param(
            'ids_only',
            'If true, only returns an Array of the IDs of assigned applets. '
            'Otherwise, returns an Array of Objects keyed with "applet" '
            '"protocol", "activities" and "items" with expanded JSON-LD as '
            'values.',
            required=False,
            default=False,
            dataType='boolean'
        )
        .errorResponse('ID was invalid.')
        .errorResponse(
            'You do not have permission to see any of this user\'s applets.',
            403
        )
        .deprecated()
    )
    def getUserApplets(self, user, role, ids_only):
        from bson.objectid import ObjectId
        reviewer = self.getCurrentUser()
        if reviewer is None:
            raise AccessException("You must be logged in to get user applets.")
        if user.get('_id') != reviewer.get('_id') and user.get(
            '_id'
        ) is not None:
            raise AccessException("You can only get your own applets.")
        role = role.lower()
        if role not in USER_ROLES.keys():
            raise RestException(
                'Invalid user role.',
                'role'
            )
        try:
            applets = AppletModel().getAppletsForUser(role, user, active=True)
            if len(applets)==0:
                return([])
            if ids_only==True:
                return([applet.get('_id') for applet in applets])
            return(
                [
                    {
                        **jsonld_expander.formatLdObject(
                            applet,
                            'applet',
                            reviewer,
                            refreshCache=False
                        ),
                        "users": AppletModel().getAppletUsers(applet, user),
                        "groups": AppletModel().getAppletGroups(
                            applet,
                            arrayOfObjects=True
                        )
                    } if role=="manager" else {
                        **jsonld_expander.formatLdObject(
                            applet,
                            'applet',
                            reviewer,
                            dropErrors=True
                        ),
                        "groups": [
                            group for group in AppletModel(
                            ).getAppletGroups(applet).get(role) if ObjectId(
                                group
                            ) in [
                                *user.get('groups', []),
                                *user.get('formerGroups', []),
                                *[invite['groupId'] for invite in [
                                    *user.get('groupInvites', []),
                                    *user.get('declinedInvites', [])
                                ]]
                            ]
                        ]
                    } for applet in applets if (
                        applet is not None and not applet.get(
                            'meta',
                            {}
                        ).get(
                            'applet',
                            {}
                        ).get('deleted')
                    )
                ]
            )
        except Exception as e:
            return(e)

    @access.public(scope=TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description('Get all your applets by role.')
        .notes(
            'This endpoint is used for users to get their applets with specified role.'
        )
        .param(
            'role',
            'One of ' + str(USER_ROLES.keys()),
            required=False,
            default='user'
        )
        .param(
            'ids_only',
            'If true, only returns an Array of the IDs of assigned applets. '
            'Otherwise, returns an Array of Objects keyed with "applet" '
            '"protocol", "activities" and "items" with expanded JSON-LD as '
            'values. This parameter takes precedence over `unexpanded`.',
            required=False,
            dataType='boolean'
        )
        .param(
            'unexpanded',
            'If true, only returns an Array of assigned applets, but only the '
            'applet-level information. Otherwise, returns an Array of Objects '
            'keyed with "applet", "protocol", "activities" and "items" with '
            'expanded JSON-LD as values.',
            required=False,
            dataType='boolean'
        )
        .param(
            'refreshCache',
            'If true, refresh user cache.',
            required=False,
            dataType='boolean'
        )
        .errorResponse('ID was invalid.')
        .errorResponse(
            'You do not have permission to see any of this user\'s applets.',
            403
        )
    )
    def getOwnApplets(
        self,
        role,
        ids_only=False,
        unexpanded=False,
        refreshCache=False
    ):
        from bson.objectid import ObjectId
        from girderformindlogger.utility.jsonld_expander import loadCache

        from girderformindlogger.utility.response import responseDateList

        reviewer = self.getCurrentUser()
        accountProfile = self.getAccountProfile()
        if reviewer is None or accountProfile is None:
            raise AccessException("You must be logged in to get user applets.")
        role = role.lower()
        if role not in USER_ROLES.keys():
            raise RestException(
                'Invalid user role.',
                'role'
            )

        applet_ids = accountProfile.get('applets', {}).get(role, [])

        if ids_only:
            return applet_ids
        applets = [AppletModel().load(ObjectId(applet_id), AccessType.READ) for applet_id in applet_ids]

        if unexpanded:
            return([{
                'applet': AppletModel().unexpanded(applet)
            } for applet in applets])

        try:
            result = []
            for applet in applets:
                if applet.get('cached'):
                    formatted = {
                        **jsonld_expander.formatLdObject(
                            applet,
                            'applet',
                            reviewer,
                            refreshCache=refreshCache,
                            responseDates=False
                        ),
                        "users": AppletModel().getAppletUsers(applet, reviewer),
                        "groups": AppletModel().getAppletGroups(
                            applet,
                            arrayOfObjects=True
                        )
                    } if role in ["coordinator", "manager"] else {
                        **jsonld_expander.formatLdObject(
                            applet,
                            'applet',
                            reviewer,
                            refreshCache=refreshCache,
                            responseDates=(role=="user")
                        ),
                        "groups": [
                            group for group in AppletModel().getAppletGroups(applet).get(
                                role
                            ) if ObjectId(
                                group
                            ) in [
                                *reviewer.get('groups', []),
                                *reviewer.get('formerGroups', []),
                                *[invite['groupId'] for invite in [
                                    *reviewer.get('groupInvites', []),
                                    *reviewer.get('declinedInvites', [])
                                ]]
                            ]
                        ]
                    }

                    try:
                        formatted["applet"]["responseDates"] = responseDateList(
                            applet.get('_id'),
                            reviewer.get('_id'),
                            reviewer
                        )
                    except:
                        formatted["applet"]["responseDates"] = []
                    result.append(formatted)

            return(result)
        except:
            import sys, traceback
            print(sys.exc_info())
            return([])

    @access.public(scope=TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description('Get all your applets by role.')
        .notes(
            'This endpoint is used for users to get their own/invited accounts.'
        )
        .errorResponse('ID was invalid.')
        .errorResponse(
            'You do not have permission to see accounts for this user.',
            403
        )
    )
    def getAccounts(self):
        user = self.getCurrentUser()

        if user is None:
            raise AccessException('You are not authorized to make request to this endpoint.')
        accounts = AccountProfile().getAccounts(user['_id'])
        fields = ['accountName', 'accountId']

        response = []
        for account in accounts:
            response.append({
                'accountName': account['accountName'],
                'accountId': account['accountId'],
                'owned': (account['_id'] == account['accountId'])
            })

        return response

    @access.public(scope=TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description('switch account.')
        .notes(
            'This endpoint is used for users to switch their current account.'
        )
        .param(
            'accountId',
            'account id to switch',
            required=True,
            default=None
        )
        .errorResponse('ID was invalid.')
        .errorResponse(
            'You do not have permission to see this account.',
            403
        )
    )
    def switchAccount(self, accountId = None):
        from bson.objectid import ObjectId
        try:
            token = self.getCurrentToken()
            user = self.getCurrentUser()
            if user:
                account = AccountProfile().findOne({'accountId': ObjectId(accountId), 'userId': user['_id']})

            if not user or not account:
                raise Exception('error.')
        except:
            raise AccessException('account does not exist or you are not allowed to access to this account')

        token['accountId'] = ObjectId(accountId)
        token = Token().save(token)

        fields = ['accountId', 'accountName', 'applets']
        tokenInfo = {
            'account': {
                field: account[field] for field in fields
            },
            'authToken': {
                'token': token['_id'],
                'expires': token['expires'],
                'scope': token['scope']
            }
        }

        if token['accountId'] == user['accountId']:
            tokenInfo['account']['isDefaultName'] = False if user['accountName'] else True

        return tokenInfo

    @access.public(scope=TokenScope.USER_INFO_READ)
    @filtermodel(model=UserModel)
    @autoDescribeRoute(
        Description('Retrieve the currently logged-in user information.')
        .responseClass('User')
    )
    def getMe(self):
        return self.getCurrentUser()

    @access.public
    @autoDescribeRoute(
        Description('Log in to the system.')
        .notes(
                'Pass your username and password using HTTP Basic Auth. Sends'
               ' a cookie that should be passed back in future requests. <br>'
               'this endpoint is used when users login mindlogger.'
        )
        .param(
            'loginAsEmail',
            "set to false when logging in as username (this value is set to true by default)",
            default = True,
            required=False
        )
        .param('Girder-OTP', 'A one-time password for this user',
               paramType='header', required=False)
        .param('deviceId', 'device id for push notifications',
               paramType='header', required=False)
        .param('timezone', 'timezone of user mobile',
               paramType='header', required=False)
        .errorResponse('Missing Authorization header.', 401)
        .errorResponse('Invalid login or password.', 403)
    )
    def login(self, loginAsEmail):
        import threading
        from girderformindlogger.utility.mail_utils import validateEmailAddress

        if not Setting().get(SettingKey.ENABLE_PASSWORD_LOGIN):
            raise RestException('Password login is disabled on this instance.')

        user, token = self.getCurrentUser(returnToken=True)

        deviceId = cherrypy.request.headers.get('deviceId', '')
        timezone = int(cherrypy.request.headers.get('timezone', 0))

        # Only create and send new cookie if user isn't already sending a valid
        # one.
        if not user:
            authHeader = cherrypy.request.headers.get('Authorization')

            if not authHeader:
                authHeader = cherrypy.request.headers.get(
                    'Girder-Authorization'
                )

            if not authHeader or not authHeader[0:6] == 'Basic ':
                raise RestException('Use HTTP Basic Authentication', 401)

            try:
                credentials = base64.b64decode(authHeader[6:]).decode('utf8')
                if ':' not in credentials:
                    raise TypeError
            except Exception:
                raise RestException('Invalid HTTP Authorization header', 401)

            login, password = credentials.split(':', 1)

            isEmail = validateEmailAddress(login)

            if not loginAsEmail and isEmail:
                raise AccessException(
                    "Please log in with a username, not an email address."
                )
            if loginAsEmail and not isEmail:
                raise AccessException(
                    "Please enter valid email address"
                )

            otpToken = cherrypy.request.headers.get('Girder-OTP')
            try:
                user = self._model.authenticate(login, password, otpToken, loginAsEmail = True)
            except:
                raise AccessException(
                    "Incorrect password for {} if that user exists".format(
                        login
                    )
                )
            if user.get('exception', None):
                raise AccessException(
                    user['exception']
                )

            if deviceId:
                user['deviceId'] = deviceId
                user['timezone'] = float(timezone)
                self._model.save(user)
                ProfileModel().updateProfiles(user, {
                    'deviceId': deviceId,
                    'timezone': float(timezone),
                    'badge': 0
                })

            setCurrentUser(user)
            token = self.sendAuthTokenCookie(user)

        account = AccountProfile().findOne({'_id': user['accountId']})

        fields = ['accountId', 'accountName', 'applets']

        tokenInfo = {
            'user': self._model.filter(user, user),
            'account': {
                field: account[field] for field in fields
            },
            'authToken': {
                'token': token['_id'],
                'expires': token['expires'],
                'scope': token['scope']
            },
            'message': 'Login succeeded.'
        }

        tokenInfo['account']['isDefaultName'] = False if user['accountName'] else True

        return tokenInfo

    @access.public
    @autoDescribeRoute(
        Description('Log out of the system.')
        .responseClass('Token')
        .notes(
            'Attempts to delete your authentication cookie. <br>'
            'This endpoint is used when users logout. <br>'
        )
    )
    def logout(self):
        token = self.getCurrentToken()
        user = self.getCurrentUser()
        if token:
            Token().remove(token)
        if user:
            ProfileModel().updateProfiles(user, {
                "deviceId": ""
            })
        self.deleteAuthTokenCookie()
        return {'message': 'Logged out.'}

    @access.public
    @filtermodel(model=UserModel, addFields={'authToken'})
    @autoDescribeRoute(
        Description('Create a new user.')
        .notes(
            'This endpoint is used to create a new account in mindlogger. <br>'
            'we save user\'s email as hashed value, so nobody will be able to see actual email address. <br>'
            'we don\'t save user\'s firstName and lastName as plain text in the database.'
        )
        .responseClass('User')
        .param('password', "The user's requested password")
        .param(
            'displayName',
            "The user's display name, usually just their first name.",
            default="",
            required=False
        )
        .param('email', "The user's email address.", required=False)
        .param('admin', 'Whether this user should be a site administrator.',
               required=False, dataType='boolean', default=False)
        .param(
            'lastName',
            'lastName of user.',
            required=False
        )
        .param(
            'firstName',
            'firstName of user.',
            required=False
        )
        .errorResponse('A parameter was invalid, or the specified login or'
                       ' email already exists in the system.')
    )
    def createUser(
        self,
        password,
        displayName="",
        email="",
        admin=False,
        lastName=None,
        firstName=None
    ):
        currentUser = self.getCurrentUser()

        regPolicy = Setting().get(SettingKey.REGISTRATION_POLICY)

        if not currentUser or not currentUser['admin']:
            admin = False
            if regPolicy == 'closed':
                raise RestException(
                    'Registration on this instance is closed. Contact an '
                    'administrator to create an account for you.')

        user = self._model.createUser(
            login="",
            password=password,
            email=email,
            firstName=displayName if len(
                displayName
            ) else firstName if firstName is not None else "",
            lastName=lastName,
            admin=admin,
            currentUser=currentUser,
            encryptEmail=True
        )

        if not currentUser and self._model.canLogin(user):
            setCurrentUser(user)
            token = self.sendAuthTokenCookie(user)
            user['authToken'] = {
                'token': token['_id'],
                'expires': token['expires']
            }

        # Assign all new users to a "New Users" Group
        newUserGroup = GroupModel().findOne({'name': 'New Users'})
        newUserGroup = newUserGroup if (
            newUserGroup is not None and bool(newUserGroup)
        ) else GroupModel(
        ).createGroup(
            name="New Users",
            creator=UserModel().findOne(
                query={'admin': True},
                sort=[('created', SortDir.ASCENDING)]
            ),
            public=False
        )
        group = GroupModel().addUser(
            newUserGroup,
            user,
            level=AccessType.READ
        )
        group['access'] = GroupModel().getFullAccessList(group)
        group['requests'] = list(GroupModel().getFullRequestList(group))

        return(user)

    @access.user
    @autoDescribeRoute(
        Description('Delete a user by ID.')
        .notes(
            'This endpoint is used to remove an account using id. <br>'
            'The removed account won\'t be reverted.'
        )
        .modelParam('id', model=UserModel, level=AccessType.ADMIN)
        .errorResponse('ID was invalid.')
        .errorResponse('You do not have permission to delete this user.', 403)
    )
    def deleteUser(self, user):
        self._model.remove(user)
        return {'message': 'Deleted user %s.' % user['login']}

    @access.user
    @autoDescribeRoute(
        Description('Get detailed information of accessible users.')
        .notes(
            'This endpoint is used to get number of folders that user has access'
        )
    )
    def getUsersDetails(self):
        nUsers = len(self._model.findWithPermissions(user=self.getCurrentUser(
        )))
        return {'nUsers': nUsers}

    @access.user
    @autoDescribeRoute(
        Description("Update a user's information.")
        .modelParam('id', model=UserModel, level=AccessType.WRITE)
        .param(
            'displayName',
            'Display name of the user, usually just their first name.',
            default="",
            required=False
        )
        .param('admin', 'Is the user a site admin (admin access required)',
               required=False, dataType='boolean')
        .param('status', 'The account status (admin access required)',
               required=False, enum=('pending', 'enabled', 'disabled'))
        .param(
             'email',
             'Deprecated. Do not use.',
             required=False,
             dataType='string'
        )
        .param(
            'firstName',
            'Deprecated. Do not use.',
            deprecated=True,
            required=False
        )
        .param(
            'lastName',
            'Deprecated. Do not use.',
            deprecated=True,
            required=False
        )
        .errorResponse()
        .errorResponse(('You do not have write access for this user.',
                        'Must be an admin to create an admin.'), 403)
    )
    def updateUser(
        self,
        user,
        displayName="",
        email="",
        admin=False,
        status=None,
        firstName=None,
        lastName=None
    ):
        user['displayName'] = displayName if len(
            displayName
        ) else firstName if firstName is not None else ""
        user['email'] = UserModel().hash(email)
        user['email_encrypted'] = True

        # Only admins can change admin state
        if admin is not None:
            if self.getCurrentUser()['admin']:
                user['admin'] = admin
            elif user['admin'] is not admin:
                raise AccessException('Only admins may change admin status.')

            # Only admins can change status
            if status is not None and status != user.get('status', 'enabled'):
                if not self.getCurrentUser()['admin']:
                    raise AccessException('Only admins may change status.')
                if user['status'] == 'pending' and status == 'enabled':
                    # Send email on the 'pending' -> 'enabled' transition
                    self._model._sendApprovedEmail(user, email)
                user['status'] = status

        try:
            self._model.save(user)
        except:
            raise RestException(
                'Update failed, and `PUT /user/{:id}` is deprecated.'
            )

        return(
            {'message': 'Update saved, but `PUT /user/{:id}` is deprecated.'}
        )

    @access.admin
    @autoDescribeRoute(
        Description("Change a user's password.")
        .notes(
            'Only administrators may use this endpoint. <br>'
            'This endpoint is used for updating password without checking original password.'
        )
        .modelParam('id', model=UserModel, level=AccessType.ADMIN)
        .param('password', "The user's new password.")
        .errorResponse('You are not an administrator.', 403)
        .errorResponse('The new password is invalid.')
    )
    def changeUserPassword(self, user, password):
        self._model.setPassword(user, password)
        return {'message': 'Password changed.'}

    @access.user
    @autoDescribeRoute(
        Description('Change your password.')
        .notes(
            'This endpoint is used when users need to update their password.'
        )
        .param('old', 'Your current password or a temporary access token.')
        .param('new', 'Your new password.')
        .errorResponse(('You are not logged in.',
                        'Your old password is incorrect.'), 401)
        .errorResponse('Your new password is invalid.')
    )
    def changePassword(self, old, new):
        user = self.getCurrentUser()
        token = None

        if not old:
            raise RestException('Old password must not be empty.')

        if (not self._model.hasPassword(user)
                or not self._model._cryptContext.verify(old, user['salt'])):
            # If not the user's actual password, check for temp access token
            token = Token().load(old, force=True, objectId=False, exc=False)
            if (not token or not token.get('userId')
                    or token['userId'] != user['_id']
                    or not Token().hasScope(token, TokenScope.TEMPORARY_USER_AUTH)):
                raise AccessException('Old password is incorrect.')

        self._model.setPassword(user, new)

        if token:
            # Remove the temporary access token if one was used
            Token().remove(token)

        return {'message': 'Password changed.'}

    @access.public
    @autoDescribeRoute(
        Description("Create a temporary access token for a user.  The user's "
                    'password is not changed.')
        .notes(
            'This endpoint is used in forgot-password functionality <br>'
            'backend sends temporary access link to user via email.'
        )
        .param('email', 'Your email address.', strip=True)
        .errorResponse('That email does not exist in the system.')
    ) ## TODO: recreate by login
    def generateTemporaryPassword(self, email):
        user = self._model.findOne({'email': self._model.hash(email.lower()), 'email_encrypted': True})

        if not user:
            user = self._model.findOne({'email': email.lower(), 'email_encrypted': {'$ne': True}})

        if not user:
            raise RestException('That email is not registered.')

        token = Token().createToken(user, days=(15/1440.0), scope=TokenScope.TEMPORARY_USER_AUTH)

        url = '%s#useraccount/%s/token/%s' % (
            mail_utils.getEmailUrlPrefix(), str(user['_id']), str(token['_id']))

        html = mail_utils.renderTemplate('temporaryAccess.mako', {
            'url': url,
            'token': str(token['_id'])
        })

        mail_utils.sendMail(
            '%s: Temporary access' % Setting().get(SettingKey.BRAND_NAME),
            html,
            [email]
        )
        return {'message': 'Sent temporary access email.'}

    @access.public
    @autoDescribeRoute(
        Description('Check if a specified token is a temporary access token '
                    'for the specified user.  If the token is valid, returns '
                    'information on the token and user.')
        .notes(
            'This endpoint is used in forgot-password functionality. <br>'
            'When users click link from their mail box frontend makes request to this endpoint.'
        )
        .modelParam('id', 'The user ID to check.', model=UserModel, force=True)
        .param('token', 'The token to check.')
        .errorResponse('The token does not grant temporary access to the specified user.', 401)
    )
    def checkTemporaryPassword(self, user, token):
        token = Token().load(
            token, user=user, level=AccessType.ADMIN, objectId=False, exc=True)
        delta = (token['expires'] - datetime.datetime.utcnow()).total_seconds()
        hasScope = Token().hasScope(token, TokenScope.TEMPORARY_USER_AUTH)

        if delta <= 0:
            raise AccessException("The token is expired")

        if token.get('userId') != user['_id'] or not hasScope:
            raise AccessException('The token does not grant temporary access to this user.')

        # Temp auth is verified, send an actual auth token now. We keep the
        # temp token around since it can still be used on a subsequent request
        # to change the password
        authToken = self.sendAuthTokenCookie(user)

        return {
            'user': self._model.filter(user, user),
            'authToken': {
                'token': authToken['_id'],
                'expires': authToken['expires'],
                'temporary': True
            },
            'message': 'Temporary access token is valid.'
        }

    @access.public
    @autoDescribeRoute(
        Description('Get detailed information about a user.')
        .notes(
            ''
        )
        .modelParam('id', model=UserModel, level=AccessType.READ)
        .errorResponse()
        .errorResponse('Read access was denied on the user.', 403)
        .deprecated()
    )
    def getUserDetails(self, user):
        return {
            'nFolders': self._model.countFolders(
                user, filterUser=self.getCurrentUser(), level=AccessType.READ)
        }

    @access.user
    @autoDescribeRoute(
        Description('Initiate the enablement of one-time passwords for this user.')
        .modelParam('id', model=UserModel, level=AccessType.ADMIN)
        .errorResponse()
        .errorResponse('Admin access was denied on the user.', 403)
    )
    def initializeOtp(self, user):
        if self._model.hasOtpEnabled(user):
            raise RestException('The user has already enabled one-time passwords.')

        otpUris = self._model.initializeOtp(user)
        self._model.save(user)

        return otpUris

    @access.user
    @autoDescribeRoute(
        Description('Finalize the enablement of one-time passwords for this user.')
        .modelParam('id', model=UserModel, level=AccessType.ADMIN)
        .param('Girder-OTP', 'A one-time password for this user', paramType='header')
        .errorResponse()
        .errorResponse('Admin access was denied on the user.', 403)
    )
    def finalizeOtp(self, user):
        otpToken = cherrypy.request.headers.get('Girder-OTP')
        if not otpToken:
            raise RestException('The "Girder-OTP" header must be provided.')

        if 'otp' not in user:
            raise RestException('The user has not initialized one-time passwords.')
        if self._model.hasOtpEnabled(user):
            raise RestException('The user has already enabled one-time passwords.')

        user['otp']['enabled'] = True
        # This will raise an exception if the verification fails, so the user will not be saved
        self._model.verifyOtp(user, otpToken)

        self._model.save(user)

    @access.user
    @autoDescribeRoute(
        Description('Disable one-time passwords for this user.')
        .modelParam('id', model=UserModel, level=AccessType.ADMIN)
        .errorResponse()
        .errorResponse('Admin access was denied on the user.', 403)
    )
    def removeOtp(self, user):
        if not self._model.hasOtpEnabled(user):
            raise RestException('The user has not enabled one-time passwords.')

        del user['otp']
        self._model.save(user)

    @access.public
    @autoDescribeRoute(
        Description(
            'Update a user profile. Requires either profile ID __OR__ applet '
            'ID and ID code.'
        )
        .jsonParam(
            'update',
            'A JSON Object with values to update, overriding existing values.',
            required=True
        )
        .param('id', 'Profile ID.', required=False)
        .param('applet', 'Applet ID.', required=False)
        .param('idCode', 'ID code.', required=False)
    )
    def updateProfile(self, update={}, id=None, applet=None, idCode=None):
        if (id is not None) and (applet is not None or idCode is not None):
            raise RestException(
                'Pass __either__ profile ID __OR__ (applet ID and ID code), '
                'not both.'
            )
        elif (id is None) and (applet is None or idCode is None):
            raise RestException(
                'Either profile ID __OR__ (applet ID and ID code) required.'
            )
        else:
            currentUser = self.getCurrentUser()
            id = id if id is not None else ProfileModel().getProfile(
                applet=AppletModel().load(applet, force=True),
                idCode=idCode,
                user=currentUser
            )
        return(ProfileModel().updateProfile(id, currentUser, update))

    @access.public
    @autoDescribeRoute(
        Description('Verify an email address using a token.')
        .notes(
            'we use this endpoint for email-verification process. <br>'
            '* this endpoint is used when users click email-verification link in their mail box.'
        )
        .modelParam('id', 'The user ID to check.', model=UserModel, force=True)
        .param('token', 'The token to check.')
        .errorResponse('The token is invalid or expired.', 401)
    )
    def verifyEmail(self, user, token):
        token = Token().load(
            token, user=user, level=AccessType.ADMIN, objectId=False, exc=True)
        delta = (token['expires'] - datetime.datetime.utcnow()).total_seconds()
        hasScope = Token().hasScope(token, TokenScope.EMAIL_VERIFICATION)

        if token.get('userId') != user['_id'] or delta <= 0 or not hasScope:
            raise AccessException('The token is invalid or expired.')

        user['emailVerified'] = True
        Token().remove(token)
        user = self._model.save(user)

        if self._model.canLogin(user):
            setCurrentUser(user)
            authToken = self.sendAuthTokenCookie(user)
            return {
                'user': self._model.filter(user, user),
                'authToken': {
                    'token': authToken['_id'],
                    'expires': authToken['expires'],
                    'scope': authToken['scope']
                },
                'message': 'Email verification succeeded.'
            }
        else:
            return {
                'user': self._model.filter(user, user),
                'message': 'Email verification succeeded.'
            }

    @access.public
    @autoDescribeRoute(
        Description('Send verification email.')
        .notes(
            'this endpoint is used for sending verificiation email to user. <br>'
            'we don\'t use this endpoint often since we automatically do it when users sign-up.'
        )
        .param('email', 'Your email.', strip=True)
        .errorResponse('That login is not registered.', 401)
    )
    def sendVerificationEmail(self, email):
        user = self._model.findOne({'email': email})

        if not user:
            raise RestException('That login is not registered.', 401)

        self._model._sendVerificationEmail(user, email)
        return {'message': 'Sent verification email.'}

    @access.user
    @autoDescribeRoute(
        Description('Change your username.')
        .notes(
            'this endpoint is used for updating user\'s login name but it is deprecated since we are using email as login'
        )
        .param('username', 'Your new username.')
        .errorResponse(('You are not logged in.',), 401)
        .deprecated()
    )
    def changeUserName(self, username):
        user = self.getCurrentUser()

        old = self._model.setUserName(user, username)

        for p in list(ProfileModel().find(query={'userId': user['_id'], 'profile': True})):
            ProfileModel()._cacheProfileDisplay(p, user, forceManager=True)

        return {'message': 'username changed from {} to {}'.format(old, username)}

    @access.user
    @autoDescribeRoute(
        Description('Change your accountName.')
        .notes(
            'this endpoint is used for updating user\'s accountName'
        )
        .param('accountName', 'Your new accountName.')
        .errorResponse(('You are not logged in.',), 401)
    )
    def changeAccountName(self, accountName):
        profile = self.getAccountProfile()
        if profile is None:
            raise AccessException("You are not authorized to change account name for this account")
        user = self.getCurrentUser()

        if user['accountId'] == profile['accountId']: # check if user is owner of account
            AccountProfile().updateAccountName(profile['accountId'], accountName)

            user['accountName'] = accountName
            self._model.save(user)
        else:
            raise AccessException("You are not authorized to change account name for this account")

        return 'success'
