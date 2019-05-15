"""Allow users to set and activate scenes."""
import asyncio
import importlib
import logging

import voluptuous as vol

from openpeerpower.const import ATTR_ENTITY_ID, CONF_PLATFORM, SERVICE_TURN_ON
import openpeerpower.helpers.config_validation as cv
from openpeerpower.helpers.entity import Entity
from openpeerpower.helpers.entity_component import EntityComponent
from openpeerpower.helpers.state import HASS_DOMAIN

DOMAIN = 'scene'
STATE = 'scening'
STATES = 'states'


def _opp_domain_validator(config):
    """Validate platform in config for openpeerpower domain."""
    if CONF_PLATFORM not in config:
        config = {CONF_PLATFORM: HASS_DOMAIN, STATES: config}

    return config


def _platform_validator(config):
    """Validate it is a valid  platform."""
    try:
        platform = importlib.import_module('.{}'.format(config[CONF_PLATFORM]),
                                           __name__)
    except ImportError:
        try:
            platform = importlib.import_module(
                'openpeerpower.components.{}.scene'.format(
                    config[CONF_PLATFORM]))
        except ImportError:
            raise vol.Invalid('Invalid platform specified') from None

    if not hasattr(platform, 'PLATFORM_SCHEMA'):
        return config

    return platform.PLATFORM_SCHEMA(config)


PLATFORM_SCHEMA = vol.Schema(
    vol.All(
        _opp_domain_validator,
        vol.Schema({
            vol.Required(CONF_PLATFORM): str
        }, extra=vol.ALLOW_EXTRA),
        _platform_validator
    ), extra=vol.ALLOW_EXTRA)

SCENE_SERVICE_SCHEMA = vol.Schema({
    vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
})


async def async_setup(opp, config):
    """Set up the scenes."""
    logger = logging.getLogger(__name__)
    component = opp.data[DOMAIN] = EntityComponent(logger, DOMAIN, opp)

    await component.async_setup(config)

    async def async_handle_scene_service(service):
        """Handle calls to the switch services."""
        target_scenes = await component.async_extract_from_service(service)

        tasks = [scene.async_activate() for scene in target_scenes]
        if tasks:
            await asyncio.wait(tasks, loop=opp.loop)

    opp.services.async_register(
        DOMAIN, SERVICE_TURN_ON, async_handle_scene_service,
        schema=SCENE_SERVICE_SCHEMA)

    return True


async def async_setup_entry(opp, entry):
    """Set up a config entry."""
    return await opp.data[DOMAIN].async_setup_entry(entry)


async def async_unload_entry(opp, entry):
    """Unload a config entry."""
    return await opp.data[DOMAIN].async_unload_entry(entry)


class Scene(Entity):
    """A scene is a group of entities and the states we want them to be."""

    @property
    def should_poll(self):
        """No polling needed."""
        return False

    @property
    def state(self):
        """Return the state of the scene."""
        return STATE

    def activate(self):
        """Activate scene. Try to get entities into requested state."""
        raise NotImplementedError()

    def async_activate(self):
        """Activate scene. Try to get entities into requested state.

        This method must be run in the event loop and returns a coroutine.
        """
        return self.opp.async_add_job(self.activate)