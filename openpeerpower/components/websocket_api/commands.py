"""Commands part of Websocket API."""
import voluptuous as vol

from openpeerpower.auth.permissions.const import POLICY_READ
from openpeerpower.const import EVENT_STATE_CHANGED, EVENT_TIME_CHANGED, MATCH_ALL
from openpeerpower.core import DOMAIN as OPP_DOMAIN, callback
from openpeerpower.exceptions import OpenPeerPowerError, ServiceNotFound, Unauthorized
from openpeerpower.helpers import config_validation as cv
from openpeerpower.helpers.event import async_track_state_change
from openpeerpower.helpers.service import async_get_all_descriptions

from . import const, decorators, messages

# mypy: allow-untyped-calls, allow-untyped-defs


@callback
def async_register_commands(opp, async_reg):
    """Register commands."""
    async_reg(opp, handle_subscribe_events)
    async_reg(opp, handle_unsubscribe_events)
    async_reg(opp, handle_call_service)
    async_reg(opp, handle_get_states)
    async_reg(opp, handle_get_services)
    async_reg(opp, handle_get_config)
    async_reg(opp, handle_ping)
    async_reg(opp, handle_render_template)


def pong_message(iden):
    """Return a pong message."""
    return {"id": iden, "type": "pong"}


@callback
@decorators.websocket_command(
    {
        vol.Required("type"): "subscribe_events",
        vol.Optional("event_type", default=MATCH_ALL): str,
    }
)
def handle_subscribe_events(opp, connection, msg):
    """Handle subscribe events command.

    Async friendly.
    """
    # Circular dep
    # pylint: disable=import-outside-toplevel
    from .permissions import SUBSCRIBE_WHITELIST

    event_type = msg["event_type"]

    if event_type not in SUBSCRIBE_WHITELIST and not connection.user.is_admin:
        raise Unauthorized

    if event_type == EVENT_STATE_CHANGED:

        @callback
        def forward_events(event):
            """Forward state changed events to websocket."""
            if not connection.user.permissions.check_entity(
                event.data["entity_id"], POLICY_READ
            ):
                return

            connection.send_message(messages.event_message(msg["id"], event))

    else:

        @callback
        def forward_events(event):
            """Forward events to websocket."""
            if event.event_type == EVENT_TIME_CHANGED:
                return

            connection.send_message(messages.event_message(msg["id"], event.as_dict()))

    connection.subscriptions[msg["id"]] = opp.bus.async_listen(
        event_type, forward_events
    )

    connection.send_message(messages.result_message(msg["id"]))


@callback
@decorators.websocket_command(
    {
        vol.Required("type"): "unsubscribe_events",
        vol.Required("subscription"): cv.positive_int,
    }
)
def handle_unsubscribe_events(opp, connection, msg):
    """Handle unsubscribe events command.

    Async friendly.
    """
    subscription = msg["subscription"]

    if subscription in connection.subscriptions:
        connection.subscriptions.pop(subscription)()
        connection.send_message(messages.result_message(msg["id"]))
    else:
        connection.send_message(
            messages.error_message(
                msg["id"], const.ERR_NOT_FOUND, "Subscription not found."
            )
        )


@decorators.websocket_command(
    {
        vol.Required("type"): "call_service",
        vol.Required("domain"): str,
        vol.Required("service"): str,
        vol.Optional("service_data"): dict,
    }
)
@decorators.async_response
async def handle_call_service(opp, connection, msg):
    """Handle call service command.

    Async friendly.
    """
    blocking = True
    if msg["domain"] == OPP_DOMAIN and msg["service"] in ["restart", "stop"]:
        blocking = False

    try:
        await opp.services.async_call(
            msg["domain"],
            msg["service"],
            msg.get("service_data"),
            blocking,
            connection.context(msg),
        )
        connection.send_message(
            messages.result_message(msg["id"], {"context": connection.context(msg)})
        )
    except ServiceNotFound as err:
        if err.domain == msg["domain"] and err.service == msg["service"]:
            connection.send_message(
                messages.error_message(
                    msg["id"], const.ERR_NOT_FOUND, "Service not found."
                )
            )
        else:
            connection.send_message(
                messages.error_message(
                    msg["id"], const.ERR_OPEN_PEER_POWER_ERROR, str(err)
                )
            )
    except OpenPeerPowerError as err:
        connection.logger.exception(err)
        connection.send_message(
            messages.error_message(msg["id"], const.ERR_OPEN_PEER_POWER_ERROR, str(err))
        )
    except Exception as err:  # pylint: disable=broad-except
        connection.logger.exception(err)
        connection.send_message(
            messages.error_message(msg["id"], const.ERR_UNKNOWN_ERROR, str(err))
        )


@callback
@decorators.websocket_command({vol.Required("type"): "get_states"})
def handle_get_states(opp, connection, msg):
    """Handle get states command.

    Async friendly.
    """
    if connection.user.permissions.access_all_entities("read"):
        states = opp.states.async_all()
    else:
        entity_perm = connection.user.permissions.check_entity
        states = [
            state
            for state in opp.states.async_all()
            if entity_perm(state.entity_id, "read")
        ]

    connection.send_message(messages.result_message(msg["id"], states))


@decorators.websocket_command({vol.Required("type"): "get_services"})
@decorators.async_response
async def handle_get_services(opp, connection, msg):
    """Handle get services command.

    Async friendly.
    """
    descriptions = await async_get_all_descriptions(opp)
    connection.send_message(messages.result_message(msg["id"], descriptions))


@callback
@decorators.websocket_command({vol.Required("type"): "get_config"})
def handle_get_config(opp, connection, msg):
    """Handle get config command.

    Async friendly.
    """
    connection.send_message(messages.result_message(msg["id"], opp.config.as_dict()))


@callback
@decorators.websocket_command({vol.Required("type"): "ping"})
def handle_ping(opp, connection, msg):
    """Handle ping command.

    Async friendly.
    """
    connection.send_message(pong_message(msg["id"]))


@callback
@decorators.websocket_command(
    {
        vol.Required("type"): "render_template",
        vol.Required("template"): cv.template,
        vol.Optional("entity_ids"): cv.entity_ids,
        vol.Optional("variables"): dict,
    }
)
def handle_render_template(opp, connection, msg):
    """Handle render_template command.

    Async friendly.
    """
    template = msg["template"]
    template.opp = opp

    variables = msg.get("variables")

    entity_ids = msg.get("entity_ids")
    if entity_ids is None:
        entity_ids = template.extract_entities(variables)

    @callback
    def state_listener(*_):
        connection.send_message(
            messages.event_message(
                msg["id"], {"result": template.async_render(variables)}
            )
        )

    if entity_ids and entity_ids != MATCH_ALL:
        connection.subscriptions[msg["id"]] = async_track_state_change(
            opp, entity_ids, state_listener
        )
    else:
        connection.subscriptions[msg["id"]] = lambda: None

    connection.send_result(msg["id"])
    state_listener()
