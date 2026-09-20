import logging
from datetime import UTC, datetime

from app.graph_client import get_authenticated_client

logger = logging.getLogger(__name__)


async def get_service_principal_details(app_id: str) -> dict[str, object]:
    """
    Fetch Azure AD service principal details including credentials, owners, and activity.
    Returns dict with status, credentials expiration, owner info, and last sign-in.
    """
    try:
        client = await get_authenticated_client()

        # Get service principal by appId
        sp_query = f"$filter=appId eq '{app_id}'"
        sp_response = await client.get(
            f"https://graph.microsoft.com/v1.0/servicePrincipals?{sp_query}&$select=id,appId,displayName,accountEnabled,createdDateTime,keyCredentials,passwordCredentials"
        )
        sp_list = sp_response.json().get("value", [])

        if not sp_list:
            raise ValueError(f"Service principal not found for appId: {app_id}")

        sp = sp_list[0]
        sp_id = sp.get("id")

        # Get owners
        owners_response = await client.get(
            f"https://graph.microsoft.com/v1.0/servicePrincipals/{sp_id}/owners?$select=id,displayName,userPrincipalName"
        )
        owners = owners_response.json().get("value", [])

        # Get last sign-in activity (from auditLogs)
        now = datetime.now(UTC)

        try:
            activity_response = await client.get(
                f"https://graph.microsoft.com/v1.0/auditLogs/signIns?$filter=servicePrincipalId eq '{sp_id}'&$top=1&$orderby=createdDateTime desc"
            )
            sign_ins = activity_response.json().get("value", [])
            last_sign_in = sign_ins[0].get("createdDateTime") if sign_ins else None
        except Exception as e:
            logger.warning(f"Could not fetch sign-in activity for {app_id}: {e}")
            last_sign_in = None

        # Parse credentials (both key and password)
        key_creds = sp.get("keyCredentials", [])
        pwd_creds = sp.get("passwordCredentials", [])

        nearest_expiration = None
        expiring_type = None
        expiring_name = None

        # Find nearest expiration from all credentials
        all_creds = [
            {**cred, "_type": "certificate"} for cred in key_creds
        ] + [
            {**cred, "_type": "secret"} for cred in pwd_creds
        ]

        for cred in all_creds:
            end_date_str = cred.get("endDateTime")
            if end_date_str:
                try:
                    exp_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                    if nearest_expiration is None or exp_date < nearest_expiration:
                        nearest_expiration = exp_date
                        expiring_type = cred.get("_type", "unknown")
                        expiring_name = cred.get("displayName", "")
                except ValueError:
                    continue

        # Calculate days remaining
        days_until_expiration = None
        if nearest_expiration:
            days_until_expiration = (nearest_expiration - now).days

        # Calculate days since last activity
        days_since_activity = None
        if last_sign_in:
            try:
                last_sign_dt = datetime.fromisoformat(last_sign_in.replace("Z", "+00:00"))
                days_since_activity = (now - last_sign_dt).days
            except ValueError:
                pass

        # Determine status
        account_enabled = sp.get("accountEnabled", False)
        owner_count = len(owners)
        has_no_owners = owner_count == 0

        status, severity = _calculate_status_and_severity(
            account_enabled=account_enabled,
            has_no_owners=has_no_owners,
            days_until_expiration=days_until_expiration,
            days_since_activity=days_since_activity,
        )

        return {
            "app_id": app_id,
            "app_display_name": sp.get("displayName", app_id),
            "account_enabled": account_enabled,
            "owner_count": owner_count,
            "has_no_owners": has_no_owners,
            "nearest_expiration_date": nearest_expiration,
            "days_until_expiration": days_until_expiration,
            "expiring_credential_type": expiring_type,
            "expiring_credential_name": expiring_name,
            "last_sign_in_datetime": last_sign_in,
            "days_since_last_activity": days_since_activity,
            "status": status,
            "severity": severity,
        }

    except Exception as e:
        logger.error(f"Failed to fetch service principal details for {app_id}: {e}")
        raise


def _calculate_status_and_severity(
    account_enabled: bool,
    has_no_owners: bool,
    days_until_expiration: int | None,
    days_since_activity: int | None,
) -> tuple[str, str]:
    """Calculate overall status and severity based on multiple factors."""

    if not account_enabled:
        return ("disabled", "medium")

    if has_no_owners:
        return ("no_owners", "high")

    # Check credential expiration
    if days_until_expiration is not None:
        if days_until_expiration < 0:
            return ("secret_expired", "critical")
        elif days_until_expiration < 7:
            return ("secret_warning_7", "high")
        elif days_until_expiration < 30:
            return ("secret_warning_30", "low")

    # Check inactivity
    if days_since_activity is not None:
        if days_since_activity > 90:
            return ("inactive_90d", "medium")
        elif days_since_activity > 30:
            return ("inactive_30d", "low")

    return ("ok", "low")


def get_status_display(status: str) -> str:
    """Map enterprise app status to display string."""
    status_map = {
        "ok": "OK",
        "disabled": "Disabled",
        "no_owners": "No Owners (⚠️)",
        "inactive_30d": "Inactive (30d)",
        "inactive_90d": "Inactive (90d)",
        "secret_warning_7": "Secret Expiring (7d)",
        "secret_warning_30": "Secret Expiring (30d)",
        "secret_expired": "Secret Expired",
    }
    return status_map.get(status, "Unknown")
