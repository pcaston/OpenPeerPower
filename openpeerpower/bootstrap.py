"""Provide methods to bootstrap a Open Peer Power instance."""
import asyncio
import logging
import logging.handlers
import os
import sys
from time import time
from collections import OrderedDict
from typing import Any, Optional, Dict, Set

import voluptuous as vol

from openpeerpower import core, config as conf_util, config_entries, loader
from openpeerpower.const import EVENT_OPENPEERPOWER_CLOSE
from openpeerpower.setup import async_setup_component
from openpeerpower.util.logging import AsyncHandler
from openpeerpower.util.package import async_get_user_site, is_virtual_env
from openpeerpower.util.yaml import clear_secret_cache
from openpeerpower.exceptions import OpenPeerPowerError
from openpeerpower.helpers import config_validation as cv

_LOGGER = logging.getLogger(__name__)

ERROR_LOG_FILENAME = 'open-peer-power.log'

# opp.data key for logging information.
DATA_LOGGING = 'logging'

DEBUGGER_INTEGRATIONS = {'ptvsd', }
CORE_INTEGRATIONS = ('openpeerpower', 'persistent_notification')
LOGGING_INTEGRATIONS = {'logger', 'system_log'}
STAGE_1_INTEGRATIONS = {
    # To record data
    'recorder',
    # To make sure we forward data to other instances
    'mqtt_eventstream',
}


async def async_from_config_dict(config: Dict[str, Any],
                                 opp: core.OpenPeerPower,
                                 config_dir: Optional[str] = None,
                                 enable_log: bool = True,
                                 verbose: bool = False,
                                 skip_pip: bool = False,
                                 log_rotate_days: Any = None,
                                 log_file: Any = None,
                                 log_no_color: bool = False) \
                           -> Optional[core.OpenPeerPower]:
    """Try to configure Open Peer Power from a configuration dictionary.

    Dynamically loads required components and its dependencies.
    This method is a coroutine.
    """
    start = time()

    if enable_log:
        async_enable_logging(opp, verbose, log_rotate_days, log_file,
                             log_no_color)

    opp.config.skip_pip = skip_pip
    if skip_pip:
        _LOGGER.warning("Skipping pip installation of required modules. "
                        "This may cause issues")

    core_config = config.get(core.DOMAIN, {})
    api_password = config.get('http', {}).get('api_password')
    trusted_networks = config.get('http', {}).get('trusted_networks')

    try:
        await conf_util.async_process_ha_core_config(
            opp, core_config, api_password, trusted_networks)
    except vol.Invalid as config_err:
        conf_util.async_log_exception(
            config_err, 'openpeerpower', core_config, opp)
        return None
    except OpenPeerPowerError:
        _LOGGER.error("Open Peer Power core failed to initialize. "
                      "Further initialization aborted")
        return None

    # Make a copy because we are mutating it.
    config = OrderedDict(config)

    # Merge packages
    await conf_util.merge_packages_config(
        opp, config, core_config.get(conf_util.CONF_PACKAGES, {}))

    opp.config_entries = config_entries.ConfigEntries(opp, config)
    await opp.config_entries.async_initialize()

    await _async_set_up_integrations(opp, config)

    stop = time()
    _LOGGER.info("Open Peer Power initialized in %.2fs", stop-start)

    # TEMP: warn users for invalid slugs
    # Remove after 0.94 or 1.0
    if cv.INVALID_SLUGS_FOUND or cv.INVALID_ENTITY_IDS_FOUND:
        msg = []

        if cv.INVALID_ENTITY_IDS_FOUND:
            msg.append(
                "Your configuration contains invalid entity ID references. "
                "Please find and update the following. "
                "This will become a breaking change."
            )
            msg.append('\n'.join('- {} -> {}'.format(*item)
                                 for item
                                 in cv.INVALID_ENTITY_IDS_FOUND.items()))

        if cv.INVALID_SLUGS_FOUND:
            msg.append(
                "Your configuration contains invalid slugs. "
                "Please find and update the following. "
                "This will become a breaking change."
            )
            msg.append('\n'.join('- {} -> {}'.format(*item)
                                 for item in cv.INVALID_SLUGS_FOUND.items()))

        opp.components.persistent_notification.async_create(
            '\n\n'.join(msg), "Config Warning", "config_warning"
        )

    # TEMP: warn users of invalid extra keys
    # Remove after 0.92
    if cv.INVALID_EXTRA_KEYS_FOUND:
        msg = []
        msg.append(
            "Your configuration contains extra keys "
            "that the platform does not support (but were silently "
            "accepted before 0.88). Please find and remove the following."
            "This will become a breaking change."
        )
        msg.append('\n'.join('- {}'.format(it)
                             for it in cv.INVALID_EXTRA_KEYS_FOUND))

        opp.components.persistent_notification.async_create(
            '\n\n'.join(msg), "Config Warning", "config_warning"
        )

    return opp


async def async_from_config_file(config_path: str,
                                 opp: core.OpenPeerPower,
                                 verbose: bool = False,
                                 skip_pip: bool = True,
                                 log_rotate_days: Any = None,
                                 log_file: Any = None,
                                 log_no_color: bool = False)\
        -> Optional[core.OpenPeerPower]:
    """Read the configuration file and try to start all the functionality.

    Will add functionality to 'opp' parameter.
    This method is a coroutine.
    """
    # Set config dir to directory holding config file
    config_dir = os.path.abspath(os.path.dirname(config_path))
    opp.config.config_dir = config_dir

    if not is_virtual_env():
        await async_mount_local_lib_path(config_dir)

    async_enable_logging(opp, verbose, log_rotate_days, log_file,
                         log_no_color)

    await opp.async_add_executor_job(
        conf_util.process_ha_config_upgrade, opp)

    try:
        config_dict = await opp.async_add_executor_job(
            conf_util.load_yaml_config_file, config_path)
    except OpenPeerPowerError as err:
        _LOGGER.error("Error loading %s: %s", config_path, err)
        return None
    finally:
        clear_secret_cache()

    return await async_from_config_dict(
        config_dict, opp, enable_log=False, skip_pip=skip_pip)


@core.callback
def async_enable_logging(opp: core.OpenPeerPower,
                         verbose: bool = False,
                         log_rotate_days: Optional[int] = None,
                         log_file: Optional[str] = None,
                         log_no_color: bool = False) -> None:
    """Set up the logging.

    This method must be run in the event loop.
    """
    fmt = ("%(asctime)s %(levelname)s (%(threadName)s) "
           "[%(name)s] %(message)s")
    datefmt = '%Y-%m-%d %H:%M:%S'

    if not log_no_color:
        try:
            from colorlog import ColoredFormatter
            # basicConfig must be called after importing colorlog in order to
            # ensure that the handlers it sets up wraps the correct streams.
            logging.basicConfig(level=logging.INFO)

            colorfmt = "%(log_color)s{}%(reset)s".format(fmt)
            logging.getLogger().handlers[0].setFormatter(ColoredFormatter(
                colorfmt,
                datefmt=datefmt,
                reset=True,
                log_colors={
                    'DEBUG': 'cyan',
                    'INFO': 'green',
                    'WARNING': 'yellow',
                    'ERROR': 'red',
                    'CRITICAL': 'red',
                }
            ))
        except ImportError:
            pass

    # If the above initialization failed for any reason, setup the default
    # formatting.  If the above succeeds, this wil result in a no-op.
    logging.basicConfig(format=fmt, datefmt=datefmt, level=logging.INFO)

    # Suppress overly verbose logs from libraries that aren't helpful
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('aiohttp.access').setLevel(logging.WARNING)

    # Log errors to a file if we have write access to file or config dir
    if log_file is None:
        err_log_path = opp.config.path(ERROR_LOG_FILENAME)
    else:
        err_log_path = os.path.abspath(log_file)

    err_path_exists = os.path.isfile(err_log_path)
    err_dir = os.path.dirname(err_log_path)

    # Check if we can write to the error log if it exists or that
    # we can create files in the containing directory if not.
    if (err_path_exists and os.access(err_log_path, os.W_OK)) or \
       (not err_path_exists and os.access(err_dir, os.W_OK)):

        if log_rotate_days:
            err_handler = logging.handlers.TimedRotatingFileHandler(
                err_log_path, when='midnight',
                backupCount=log_rotate_days)  # type: logging.FileHandler
        else:
            err_handler = logging.FileHandler(
                err_log_path, mode='w', delay=True)

        err_handler.setLevel(logging.INFO if verbose else logging.WARNING)
        err_handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))

        async_handler = AsyncHandler(opp.loop, err_handler)

        async def async_stop_async_handler(_: Any) -> None:
            """Cleanup async handler."""
            logging.getLogger('').removeHandler(async_handler)  # type: ignore
            await async_handler.async_close(blocking=True)

        opp.bus.async_listen_once(
            EVENT_OPENPEERPOWER_CLOSE, async_stop_async_handler)

        logger = logging.getLogger('')
        logger.addHandler(async_handler)  # type: ignore
        logger.setLevel(logging.INFO)

        # Save the log file location for access by other components.
        opp.data[DATA_LOGGING] = err_log_path
    else:
        _LOGGER.error(
            "Unable to set up error log %s (access denied)", err_log_path)


async def async_mount_local_lib_path(config_dir: str) -> str:
    """Add local library to Python Path.

    This function is a coroutine.
    """
    deps_dir = os.path.join(config_dir, 'deps')
    lib_dir = await async_get_user_site(deps_dir)
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)
    return deps_dir


@core.callback
def _get_domains(opp: core.OpenPeerPower, config: Dict[str, Any]) -> Set[str]:
    """Get domains of components to set up."""
    # Filter out the repeating and common config section [openpeerpower]
    domains = set(key.split(' ')[0] for key in config.keys()
                  if key != core.DOMAIN)

    # Add config entry domains
    domains.update(opp.config_entries.async_domains())  # type: ignore

    # Make sure the Opp.io component is loaded
    if 'HASSIO' in os.environ:
        domains.add('oppio')

    return domains


async def _async_set_up_integrations(
        opp: core.OpenPeerPower, config: Dict[str, Any]) -> None:
    """Set up all the integrations."""
    domains = _get_domains(opp, config)

    # Start up debuggers. Start these first in case they want to wait.
    debuggers = domains & DEBUGGER_INTEGRATIONS
    if debuggers:
        _LOGGER.debug("Starting up debuggers %s", debuggers)
        await asyncio.gather(*[
            async_setup_component(opp, domain, config)
            for domain in debuggers])
        domains -= DEBUGGER_INTEGRATIONS

    # Resolve all dependencies of all components so we can find the logging
    # and integrations that need faster initialization.
    resolved_domains_task = asyncio.gather(*[
        loader.async_component_dependencies(opp, domain)
        for domain in domains
    ], return_exceptions=True)

    # Set up core.
    _LOGGER.debug("Setting up %s", CORE_INTEGRATIONS)

    if not all(await asyncio.gather(*[
            async_setup_component(opp, domain, config)
            for domain in CORE_INTEGRATIONS
    ])):
        _LOGGER.error("Open Peer Power core failed to initialize. "
                      "Further initialization aborted")
        return

    _LOGGER.debug("Open Peer Power core initialized")

    # Finish resolving domains
    for dep_domains in await resolved_domains_task:
        # Result is either a set or an exception. We ignore exceptions
        # It will be properly handled during setup of the domain.
        if isinstance(dep_domains, set):
            domains.update(dep_domains)

    # setup components
    logging_domains = domains & LOGGING_INTEGRATIONS
    stage_1_domains = domains & STAGE_1_INTEGRATIONS
    stage_2_domains = domains - logging_domains - stage_1_domains

    if logging_domains:
        _LOGGER.info("Setting up %s", logging_domains)

        await asyncio.gather(*[
            async_setup_component(opp, domain, config)
            for domain in logging_domains
        ])

    # Kick off loading the registries. They don't need to be awaited.
    asyncio.gather(
        opp.helpers.device_registry.async_get_registry(),
        opp.helpers.entity_registry.async_get_registry(),
        opp.helpers.area_registry.async_get_registry())

    if stage_1_domains:
        await asyncio.gather(*[
            async_setup_component(opp, domain, config)
            for domain in stage_1_domains
        ])

    # Load all integrations
    after_dependencies = {}  # type: Dict[str, Set[str]]

    for int_or_exc in await asyncio.gather(*[
            loader.async_get_integration(opp, domain)
            for domain in stage_2_domains
    ], return_exceptions=True):
        # Exceptions are handled in async_setup_component.
        if (isinstance(int_or_exc, loader.Integration) and
                int_or_exc.after_dependencies):
            after_dependencies[int_or_exc.domain] = set(
                int_or_exc.after_dependencies
            )

    last_load = None
    while stage_2_domains:
        domains_to_load = set()

        for domain in stage_2_domains:
            after_deps = after_dependencies.get(domain)
            # Load if integration has no after_dependencies or they are
            # all loaded
            if (not after_deps or
                    not after_deps-opp.config.components):
                domains_to_load.add(domain)

        if not domains_to_load or domains_to_load == last_load:
            break

        _LOGGER.debug("Setting up %s", domains_to_load)

        await asyncio.gather(*[
            async_setup_component(opp, domain, config)
            for domain in domains_to_load
        ])

        last_load = domains_to_load
        stage_2_domains -= domains_to_load

    # These are stage 2 domains that never have their after_dependencies
    # satisfied.
    if stage_2_domains:
        _LOGGER.debug("Final set up: %s", stage_2_domains)

        await asyncio.gather(*[
            async_setup_component(opp, domain, config)
            for domain in stage_2_domains
        ])

    # Wrap up startup
    await opp.async_block_till_done()
