"""WebSocket based API for Home Assistant."""
from openpeerpower.core import callback
from openpeerpower.loader import bind_opp

from . import commands, connection, const, decorators, http, messages

DOMAIN = const.DOMAIN

DEPENDENCIES = ('http',)

# Backwards compat / Make it easier to integrate
# pylint: disable=invalid-name
ActiveConnection = connection.ActiveConnection
BASE_COMMAND_MESSAGE_SCHEMA = messages.BASE_COMMAND_MESSAGE_SCHEMA
error_message = messages.error_message
result_message = messages.result_message
event_message = messages.event_message
async_response = decorators.async_response
require_admin = decorators.require_admin
ws_require_user = decorators.ws_require_user
websocket_command = decorators.websocket_command
# pylint: enable=invalid-name


@bind_opp
@callback
def async_register_command(opp, command_or_handler, handler=None,
                           schema=None):
    """Register a websocket command."""
    # pylint: disable=protected-access
    if handler is None:
        handler = command_or_handler
        command = handler._ws_command
        schema = handler._ws_schema
    else:
        command = command_or_handler
    handlers = opp.data.get(DOMAIN)
    if handlers is None:
        handlers = opp.data[DOMAIN] = {}
    handlers[command] = (handler, schema)


async def async_setup(opp, config):
    """Initialize the websocket API."""
    opp.http.register_view(http.WebsocketAPIView)
    commands.async_register_commands(opp, async_register_command)
    return True