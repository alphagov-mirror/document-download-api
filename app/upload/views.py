from io import BytesIO
from itertools import chain
from base64 import b64decode

from flask import abort, Blueprint, current_app, jsonify, request

from app import document_store, antivirus_client
from app.utils import get_mime_type
from app.utils.antivirus import AntivirusError
from app.utils.authentication import check_auth
from app.utils.urls import get_direct_file_url, get_frontend_download_url

upload_blueprint = Blueprint('upload', __name__, url_prefix='')
upload_blueprint.before_request(check_auth)


@upload_blueprint.route('/services/<uuid:service_id>/documents', methods=['POST'])
def upload_document(service_id):
    no_document_error = jsonify(error='No document upload'), 400

    if request.is_json:
        if 'document' not in request.json:
            return no_document_error
        raw_content = b64decode(request.json['document'])
        if len(raw_content) > current_app.config['MAX_CONTENT_LENGTH']:
            abort(413)
        file_data = BytesIO(raw_content)
        is_csv = request.json.get('is_csv', False)
    else:
        if 'document' not in request.files:
            return no_document_error
        file_data = request.files['document']
        is_csv = False

    if not isinstance(is_csv, bool):
        return jsonify(error='Value for is_csv must be a boolean'), 400

    mimetype = get_mime_type(file_data)
    if mimetype not in chain(*current_app.config['ALLOWED_FILE_TYPES'].values()):
        allowed_file_types = ', '.join(sorted(f"'.{x}'" for x in current_app.config['ALLOWED_FILE_TYPES'].keys()))
        return jsonify(error=f"Unsupported file type '{mimetype}'. Supported types are: {allowed_file_types}"), 400

    # Our mimetype auto-detection resolves CSV content as text/plain, so we use
    # an explicit POST body parameter `is_csv` from the caller to resolve it as text/csv
    if is_csv and mimetype == 'text/plain':
        mimetype = 'text/csv'

    if current_app.config['ANTIVIRUS_ENABLED']:
        try:
            virus_free = antivirus_client.scan(file_data)
        except AntivirusError:
            return jsonify(error='Antivirus API error'), 503

        if not virus_free:
            return jsonify(error="File did not pass the virus scan"), 400

    document = document_store.put(service_id, file_data, mimetype=mimetype)

    return jsonify(
        status='ok',
        document={
            'id': document['id'],
            'direct_file_url': get_direct_file_url(
                service_id=service_id,
                document_id=document['id'],
                key=document['encryption_key'],
            ),
            'url': get_frontend_download_url(
                service_id=service_id,
                document_id=document['id'],
                key=document['encryption_key'],
            ),
            'mimetype': mimetype,
        }
    ), 201
