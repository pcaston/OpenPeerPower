"""Config flow for Mobile App."""
import uuid

from openpeerpower import config_entries
from openpeerpower.components import person
from openpeerpower.helpers import entity_registry

from .const import ATTR_APP_ID, ATTR_DEVICE_ID, ATTR_DEVICE_NAME, CONF_USER_ID, DOMAIN


@config_entries.HANDLERS.register(DOMAIN)
class MobileAppFlowHandler(config_entries.ConfigFlow):
    """Handle a Mobile App config flow."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_PUSH

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        placeholders = {
            "apps_url": "https://www.open-peer-power.io/components/mobile_app/#apps"
        }

        return self.async_abort(
            reason="install_app", description_placeholders=placeholders
        )

    async def async_step_registration(self, user_input=None):
        """Handle a flow initialized during registration."""
        if ATTR_DEVICE_ID in user_input:
            # Unique ID is combi of app + device ID.
            await self.async_set_unique_id(
                f"{user_input[ATTR_APP_ID]}-{user_input[ATTR_DEVICE_ID]}"
            )
        else:
            user_input[ATTR_DEVICE_ID] = str(uuid.uuid4()).replace("-", "")

        # Register device tracker entity and add to person registering app
        ent_reg = await entity_registry.async_get_registry(self.opp)
        devt_entry = ent_reg.async_get_or_create(
            "device_tracker",
            DOMAIN,
            user_input[ATTR_DEVICE_ID],
            suggested_object_id=user_input[ATTR_DEVICE_NAME],
        )
        await person.async_add_user_device_tracker(
            self.opp, user_input[CONF_USER_ID], devt_entry.entity_id
        )

        return self.async_create_entry(
            title=user_input[ATTR_DEVICE_NAME], data=user_input
        )
