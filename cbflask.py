# Configurable
# Connection string to use
COUCHBASE_CONNSTR = 'couchbase://localhost'
# Password for bucket, if applicable
COUCHBASE_PASSWORD = None

from flask import Flask, g, abort, request, json, make_response, Response
from couchbase.bucket import Bucket
from couchbase.n1ql import N1QLQuery
import couchbase.exceptions as cb_errors

app = Flask(__name__)
app.config.from_object(__name__)


def get_db():
    """
    Helper function to initialize and retrieve the Bucket object if
    not already present
    """
    if not hasattr(g, 'cb_bucket'):
        g.cb_bucket = Bucket(app.config['COUCHBASE_CONNSTR'],
                             password=app.config['COUCHBASE_PASSWORD'])
    return g.cb_bucket


def ensure_primary_index(cb, bucket_name=None):
    """
    Ensures the primary index for a given bucket exists, so that it
    may be queried. Ideally you would create optimized indexes whic
    can be used to lookup commonly queried fields efficiently.
    :param cb: The bucket
    :param bucket_name: The name of the bucket which needs an index
    """

    # See if we've performed this check in the past
    if not hasattr(g, 'cb_primary_indexes'):
        g.cb_primary_indexes = set()
    if bucket_name in g.cb_primary_indexes:
        return

    if not bucket_name:
        bucket_name = cb.bucket

    q = N1QLQuery('SELECT COUNT(*) AS c FROM system:indexes '
                  'WHERE keyspace_id=$1 AND is_primary=true', bucket_name)
    num = cb.n1ql_query(q).get_single_result()['c']

    if not num:
        cb.n1ql_query(
            'CREATE PRIMARY INDEX ON `{0}`'.format(bucket_name)).execute()

    g.cb_primary_indexes.add(bucket_name)


@app.route('/id/<doc_id>', methods=['GET'])
def get_item(doc_id):
    try:
        rv = get_db().get(doc_id)
        value = json.dumps(rv.value)
        resp = make_response(value)
        resp.headers['Content-Type'] = 'application/json'
        return resp
    except cb_errors.NotFoundError:
        abort(404)


@app.route('/id/<doc_id>', methods=['PUT', 'POST'])
def store_item(doc_id):
    bkt = get_db()
    meth = bkt.upsert if request.method == 'PUT' else bkt.insert
    value = request.get_json(silent=False, force=True)

    if not value:
        abort(400, 'Cannot store empty value')
    try:
        meth(doc_id, value)
        return '', 200
    except cb_errors.KeyExistsError:
        abort(500, 'Cannot create new item (use PUT instead)')


@app.route('/id/<doc_id>', methods=['DELETE'])
def del_item(doc_id):
    try:
        get_db().remove(doc_id)
        return '', 200
    except cb_errors.NotFoundError:
        return 'Item already deleted', 404


@app.route('/query/<bucket>')
def query_items(bucket):
    cb = get_db()
    ensure_primary_index(cb, bucket)

    qstr = 'SELECT * FROM `{0}`'.format(bucket)
    placeholders = []

    if request.args:
        qstr += 'WHERE '
        where = []
        i = 1
        for field, value in request.args.items():
            where.append('`{0}`=${1}'.format(field, i))
            placeholders.append(value)
            i += 1
        qstr += 'AND '.join(where)

    q = N1QLQuery(qstr, *placeholders)
    rows = [x[bucket] for x in cb.n1ql_query(q)]
    return make_response(json.dumps(rows)), 200

if __name__ == '__main__':
    app.debug = True
    app.run()