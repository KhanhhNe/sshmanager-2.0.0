import asyncio
import json
import logging
import os.path
import re
import socket
from typing import Awaitable, List

import aiohttp
import asyncssh
from aiohttp_socks import ProxyConnector


def get_ipv4_address():
    """
    Get this machine's local IPv4 address
    :return: IP address in LAN
    """
    hostname = socket.gethostname()
    return socket.gethostbyname(hostname)


def get_free_port():
    """
    Get a free port in local machine
    :return: Port number
    """
    sock = socket.socket()
    sock.bind(('', 0))
    return sock.getsockname()[1]


def parse_ssh_file(file_content):
    """
    Parse SSH from file content. Expects IP, username, password, delimiting by
    some delimiter.

    :param file_content: Parsing file content
    :return: List of {ip: "...", username: "...", password: "..."}
    """
    results = []
    for line in file_content.splitlines():
        match = re.search(r'((?:[0-9]{1,3}\.){3}[0-9]{1,3})[;,|]([^;,|]*)[;,|]([^;,|]*)', line)
        if match:
            ip, username, password = match.groups()
            results.append({
                'ip': ip,
                'username': username,
                'password': password
            })
    return results


async def get_proxy_ip(proxy_address, tries=0) -> str:
    """
    Retrieves proxy's real IP address. Returns empty string if failed.

    :param proxy_address: Proxy connection address in <protocol>://<ip>:<port>
    :param tries: Total request tries
    :return: Proxy real IP address on success connection, empty string otherwise
    """
    # noinspection PyBroadException
    try:
        connector = ProxyConnector.from_url(proxy_address, enable_cleanup_closed=True)
        async with aiohttp.ClientSession(connector=connector) as client:
            # noinspection PyBroadException
            try:
                resp = await client.get('https://api.ipify.org?format=text')
                return await resp.text()
            except Exception:
                resp = await client.get('https://ip.seeip.org')
                return await resp.text()
    except Exception:
        if not tries:
            return ''
        return await get_proxy_ip(proxy_address, tries=tries - 1)


async def kill_ssh_connection(connection: asyncssh.SSHClientConnection):
    """
    Kill the SSH connection.

    :param connection: SSH connection
    """
    await connection.__aexit__(None, None, None)


def configure_logging():
    """
    Configure console logging and file logging.
    """

    def logging_filter(record: logging.LogRecord):
        if any([
            record.exc_info and record.exc_info[0] in [BrokenPipeError],
            record.name == 'Ssh'
        ]):
            return False
        return True

    # Console logging handler
    console_logging = logging.StreamHandler()
    console_logging.setLevel(logging.INFO
                             if not os.environ.get('DEBUG')
                             else logging.DEBUG)
    console_logging.addFilter(logging_filter)

    # File logging handler
    file_logging = logging.FileHandler('data/debug.log', mode='w')
    file_logging.setLevel(logging.DEBUG)
    file_logging.addFilter(logging_filter)

    # SSH debug logging handler
    ssh_logging = logging.FileHandler('data/ssh-debug.log', mode='w')
    ssh_logging.setLevel(logging.DEBUG)
    ssh_logging.addFilter(lambda rec: rec.name == 'Ssh')

    # Config the logging module
    log_config = json.load(open('logging_config.json'))
    formatter_config = log_config['formatters']['standard']
    logging.basicConfig(level=logging.DEBUG,
                        format=formatter_config['format'],
                        datefmt=formatter_config['datefmt'],
                        handlers=[file_logging, console_logging, ssh_logging],
                        force=True)

    for logger in ['multipart.multipart', 'charset_normalizer', 'asyncio']:
        logging.getLogger(logger).setLevel(logging.WARNING)


async def get_first_success(aws: List[Awaitable]):
    """
    Awaitable that returns first successful result.

    :param aws: Awaitable list of awaitables
    :return: First successful result
    :raise: Exception if all awaitables failed
    """
    exception = None
    tasks = [asyncio.ensure_future(aw) for aw in aws]
    for future in asyncio.as_completed(tasks):
        try:
            result = await future
            asyncio.ensure_future(asyncio.gather(*tasks, return_exceptions=True))
            return result
        except Exception as exc:
            exception = exc
    if not isinstance(exception, asyncio.CancelledError):
        raise exception
    else:
        raise asyncio.TimeoutError()
