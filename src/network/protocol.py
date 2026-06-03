import struct


KEY_TO_ID = {
    "type": 0, "player_id": 1, "data": 2, "name": 3, "skin_id": 4,
    "token": 5, "seq": 6, "pos": 7, "health_delta": 8, "ammo_delta": 9,
    "enemy_damage": 10, "remove_pickup": 11, "got_keycard": 12, "door_closed": 13,
    "elevator_waiting": 14, "state": 15, "enemy_index": 16, "damage": 17,
    "angle": 18, "score": 19, "id": 20, "players": 21, "enemies": 22,
    "objects": 23, "global_health": 24, "global_ammo": 25, "keycard_acquired": 26,
    "level": 27, "escaped": 28, "elevator_ready": 29, "elevator_transition": 30,
    "elevator_wait_timer": 31, "jan_spotted": 32, "exit_pos": 33, "health": 34,
    "ammo": 35, "keycard": 36, "exit": 37, "pid": 38, "uploader": 39,
    "skin_manifest": 41, "success": 42, "error": 43,
    "chunk": 44, "total": 45,
    "countdown": 50, "game_active": 51, "ready": 52,
}

ID_TO_KEY = {v: k for k, v in KEY_TO_ID.items()}

PACKET_TYPE_TO_ID = {
    "connect": 0, "register": 1, "pos_update": 2, "start_game": 3,
    "disconnect": 4, "select_skin": 5, "request_lobby": 6, "ping": 7,
    "skin_request": 8, "skin_upload": 9, "accept": 10, "state": 11,
    "lobby_info": 12, "game_start": 13, "skin_manifest_update": 14,
    "skin_data": 15, "skin_chunk": 16, "skin_upload_ack": 17,
    "server_stopped": 18, "join_game": 20, "ready": 21, "pong": 22,
}

ID_TO_PACKET_TYPE = {v: k for k, v in PACKET_TYPE_TO_ID.items()}

NONE_TAG = 0
BOOL_TAG = 1
INT32_TAG = 2
FLOAT_TAG = 3
STRING_TAG = 4
BYTES_TAG = 5
POS_TAG = 6
LIST_TAG = 7
DICT_TAG = 8
TERMINATOR = 0xFF


def encode_value(buf, value):
    if value is None:
        buf.append(NONE_TAG)
    elif isinstance(value, bool):
        buf.append(BOOL_TAG)
        buf.append(1 if value else 0)
    elif isinstance(value, int):
        buf.append(INT32_TAG)
        buf.extend(value.to_bytes(4, 'big', signed=True))
    elif isinstance(value, float):
        buf.append(FLOAT_TAG)
        buf.extend(struct.pack('>f', value))
    elif isinstance(value, str):
        encoded = value.encode('utf-8')
        buf.append(STRING_TAG)
        buf.extend(len(encoded).to_bytes(2, 'big'))
        buf.extend(encoded)
    elif isinstance(value, bytes):
        buf.append(BYTES_TAG)
        buf.extend(len(value).to_bytes(4, 'big'))
        buf.extend(value)
    elif isinstance(value, tuple) and len(value) == 2 and all(isinstance(v, (int, float)) for v in value):
        x, y = float(value[0]), float(value[1])
        buf.append(POS_TAG)
        buf.extend(struct.pack('>f', x))
        buf.extend(struct.pack('>f', y))
    elif isinstance(value, (list, tuple)):
        buf.append(LIST_TAG)
        buf.extend(len(value).to_bytes(4, 'big'))
        for item in value:
            encode_value(buf, item)
    elif isinstance(value, dict):
        buf.append(DICT_TAG)
        buf.extend(len(value).to_bytes(2, 'big'))
        for k, v in value.items():
            kid = KEY_TO_ID.get(k, 255)
            buf.append(kid)
            encode_value(buf, v)
    else:
        buf.append(NONE_TAG)


def decode_value(data, offset):
    tag = data[offset]
    offset += 1
    if tag == NONE_TAG:
        return None, offset
    elif tag == BOOL_TAG:
        return bool(data[offset]), offset + 1
    elif tag == INT32_TAG:
        v = int.from_bytes(data[offset:offset+4], 'big', signed=True)
        return v, offset + 4
    elif tag == FLOAT_TAG:
        v = struct.unpack('>f', data[offset:offset+4])[0]
        return v, offset + 4
    elif tag == STRING_TAG:
        length = int.from_bytes(data[offset:offset+2], 'big')
        offset += 2
        v = data[offset:offset+length].decode('utf-8')
        return v, offset + length
    elif tag == BYTES_TAG:
        length = int.from_bytes(data[offset:offset+4], 'big')
        offset += 4
        v = data[offset:offset+length]
        return v, offset + length
    elif tag == POS_TAG:
        x = struct.unpack('>f', data[offset:offset+4])[0]
        y = struct.unpack('>f', data[offset+4:offset+8])[0]
        return (x, y), offset + 8
    elif tag == LIST_TAG:
        count = int.from_bytes(data[offset:offset+4], 'big')
        offset += 4
        items = []
        for _ in range(count):
            item, offset = decode_value(data, offset)
            items.append(item)
        return items, offset
    elif tag == DICT_TAG:
        count = int.from_bytes(data[offset:offset+2], 'big')
        offset += 2
        d = {}
        for _ in range(count):
            kid = data[offset]
            offset += 1
            val, offset = decode_value(data, offset)
            key = ID_TO_KEY.get(kid, f"key_{kid}")
            d[key] = val
        return d, offset
    return None, offset


def encode_packet(packet):
    pkt_type = packet.get("type", "")
    pkt_id = PACKET_TYPE_TO_ID.get(pkt_type, 255)
    buf = bytearray()
    buf.append(pkt_id)
    for key, value in packet.items():
        if key == "type":
            continue
        kid = KEY_TO_ID.get(key, 255)
        buf.append(kid)
        encode_value(buf, value)
    buf.append(TERMINATOR)
    return bytes(buf)


def decode_packet(data):
    if not data:
        return None
    pkt_id = data[0]
    pkt_type = ID_TO_PACKET_TYPE.get(pkt_id, "unknown")
    packet = {"type": pkt_type}
    offset = 1
    while offset < len(data):
        kid = data[offset]
        offset += 1
        if kid == TERMINATOR:
            break
        val, offset = decode_value(data, offset)
        key = ID_TO_KEY.get(kid, f"key_{kid}")
        packet[key] = val
    return packet
