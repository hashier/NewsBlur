import datetime
import pickle
import base64
from utils import log as logging
from oauth2client.client import OAuth2WebServerFlow, FlowExchangeError
from bson.errors import InvalidStringData
import uuid
from django.contrib.sites.models import Site
from django.contrib.auth.models import User
# from django.db import IntegrityError
from django.http import HttpResponse, HttpResponseRedirect
from django.conf import settings
from django.core.urlresolvers import reverse
from django.template import RequestContext
from django.contrib.auth import login as login_user
from django.shortcuts import render_to_response
from apps.reader.forms import SignupForm
from apps.reader.models import UserSubscription
from apps.feed_import.models import OAuthToken
from apps.feed_import.models import OPMLImporter, OPMLExporter, UploadedOPML
from apps.feed_import.tasks import ProcessOPML
from utils import json_functions as json
from utils.user_functions import ajax_login_required, get_user
from utils.feed_functions import TimeoutError


@ajax_login_required
def opml_upload(request):
    xml_opml = None
    message = "OK"
    code = 1
    payload = {}
    
    if request.method == 'POST':
        if 'file' in request.FILES:
            logging.user(request, "~FR~SBOPML upload starting...")
            file = request.FILES['file']
            xml_opml = str(file.read().decode('utf-8', 'ignore'))
            try:
                UploadedOPML.objects.create(user_id=request.user.pk, opml_file=xml_opml)
            except (UnicodeDecodeError, InvalidStringData):
                folders = None
                code = -1
                message = "There was a Unicode decode error when reading your OPML file."
            
            opml_importer = OPMLImporter(xml_opml, request.user)
            try:
                folders = opml_importer.try_processing()
            except TimeoutError:
                folders = None
                ProcessOPML.delay(request.user.pk)
                feed_count = opml_importer.count_feeds_in_opml()
                logging.user(request, "~FR~SBOPML upload took too long, found %s feeds. Tasking..." % feed_count)
                payload = dict(folders=folders, delayed=True, feed_count=feed_count)
                code = 2
                message = ""
            except AttributeError:
                code = -1
                message = "OPML import failed. Couldn't parse XML file."
                folders = None

            if folders:
                code = 1
                feeds = UserSubscription.objects.filter(user=request.user).values()
                payload = dict(folders=folders, feeds=feeds)
                logging.user(request, "~FR~SBOPML Upload: ~SK%s~SN~SB~FR feeds" % (len(feeds)))
            
        else:
            message = "Attach an .opml file."
            code = -1
            
    return HttpResponse(json.encode(dict(message=message, code=code, payload=payload)),
                        mimetype='text/html')

def opml_export(request):
    user     = get_user(request)
    now      = datetime.datetime.now()
    if request.REQUEST.get('user_id') and user.is_staff:
        user = User.objects.get(pk=request.REQUEST['user_id'])
    exporter = OPMLExporter(user)
    opml     = exporter.process()
    
    response = HttpResponse(opml, mimetype='text/xml')
    response['Content-Disposition'] = 'attachment; filename=NewsBlur-%s-%s' % (
        user.username,
        now.strftime('%Y-%m-%d')
    )
    
    return response


