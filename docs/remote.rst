Remote
========

annotate
--------
::

def annotate(image_path, *, profile=None, base_url=None, wait=True,
             poll_interval=5.0, timeout=None, results_dir=None,
             verify=None, submit=True, progress=None):
    """ Annotate a slide on a compatible remote server.

    """

status
--------
::

def status(image_path, **kwargs):
    """ Report on the job for image_path without uploading anything.

    """

RemoteClient
--------
::

def RemoteClient(base_url=None, *, token=None, timeout=None, verify=None,
                 profile=None, progress=False):
    """ Thin wrapper over the remote annotation HTTP protocol.

    """

capabilities
--------
::

def capabilities(self):
    """ Describe the server: protocol id, auth methods, upload limits.

    """

check_protocol
--------
::

def check_protocol(self, capabilities=None):
    """ Verify the server speaks this client's protocol version.

    """

login
--------
::

def login(self, username, password):
    """ Exchange a username and password for a bearer token.

    """

whoami
--------
::

def whoami(self, token=None):
    """ Return the identity behind a token.

    """

submit_job
--------
::

def submit_job(self, path, *, token=None, timeout=None, progress=None):
    """ Upload a slide and create an annotation job.

    """

get_job
--------
::

def get_job(self, job_id, *, token=None):
    """ Fetch the state of a job.

    """

artifacts
--------
::

def artifacts(self, job_id, *, token=None):
    """ List the result files a completed job produced.

    """

download_artifact
--------
::

def download_artifact(self, artifact, dest_path, *, token=None,
                      timeout=None, progress=None):
    """ Stream one artifact to dest_path.

    """
