from . import models


def post_init_hook(cr, registry):
    """Backfill the durable ever_verified marker from real recorded state.

    Any credential currently verified or superseded was, by definition, verified
    at some point, so its source file must stay protected. We derive this only
    from unambiguous recorded state and never fabricate verification: a 'rejected'
    record is NOT backfilled here (older code also stamped verified_on on a plain
    rejection, so that column is ambiguous for rejected rows). Going forward,
    action_verify sets ever_verified before any later rejection, so revoked
    evidence keeps its protection without guesswork.
    """
    cr.execute(
        "UPDATE fleetflow_credential SET ever_verified = TRUE "
        "WHERE ever_verified IS NOT TRUE AND state IN ('verified', 'superseded')"
    )
