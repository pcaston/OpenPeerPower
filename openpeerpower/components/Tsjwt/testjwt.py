#!/usr/bin/python3
#
# Copyright (c) 2017-2018, Fabian Affolter <fabian@affolter-engineering.ch>
# Released under the ASL 2.0 license. See LICENSE.md file for details.
#
import asyncio
import json
import asyncws

#ACCESS_TOKEN = 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiI3ZDg2Mzc3NzIwYjQ0M2YyOWI2MzE2ZTdmMjI3Njc0OCIsImlhdCI6MTU0MzYwMTY1OCwiZXhwIjoxODU4OTYxNjU4fQ.uSatzdHOC-ozC9OnI0pUk63Mtuawy7bauRG6k-swP9g'


async def main():
    """Simple WebSocket client for Home Assistant."""
    websocket = await asyncws.connect('ws://localhost:8123/api/websocket')
    while True:
        message = await websocket.recv()
        msg = json.loads(message)
        
        if msg['type'] == 'auth_required':
            await websocket.send(json.dumps(
            { 'type': 'register', 'client_id': 'http://127.0.0.1:8081', 'name': 'Paul', 'username': 'paul','password': 'Boswald0'}
            ))
        
        
        if msg['type'] == 'auth_ok':
            await websocket.send(json.dumps(
            {'id': 1, 'type': 'subscribe_events', 'event_type': 'state_changed'}
            ))

        print(message)
        if message is None:
            break

loop = asyncio.get_event_loop()
loop.run_until_complete(main())
loop.close()
