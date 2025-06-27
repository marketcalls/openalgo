import datetime
import json
import ssl

import websocket
from utils.logging import get_logger

logger = get_logger(__name__)


# from neo_api_client.logger import logger

isEncyptOut = False
isEncyptIn = True

MAX_SCRIPS = 100
topic_list = {}
counter = 0
FieldTypes = {
    'FLOAT32': 1,
    'LONG': 2,
    'DATE': 3,
    'STRING': 4
}
TRASH_VAL = -2147483648
STRING_INDEX = {
    'NAME': 51,
    'SYMBOL': 52,
    'EXCHG': 53,
    'TSYMBOL': 54
}
DEPTH_INDEX = {
    "MULTIPLIER": 32,
    "PRECISION": 33
}
BinRespTypes = {
    "CONNECTION_TYPE": 1,
    "THROTTLING_TYPE": 2,
    "ACK_TYPE": 3,
    "SUBSCRIBE_TYPE": 4,
    "UNSUBSCRIBE_TYPE": 5,
    "DATA_TYPE": 6,
    "CHPAUSE_TYPE": 7,
    "CHRESUME_TYPE": 8,
    "SNAPSHOT": 9,
    "OPC_SUBSCRIBE": 10
}
# ws = None
BinRespStat = {
    "OK": "K",
    "NOT_OK": "N"
}
ResponseTypes = {
    "SNAP": 83,
    "UPDATE": 85
}
STAT = {
    "OK": "Ok",
    "NOT_OK": "NotOk"
}
RespTypeValues = {
    "CONN": "cn",
    "SUBS": "sub",
    "UNSUBS": "unsub",
    "SNAP": "snap",
    "CHANNELR": "cr",
    "CHANNELP": "cp",
    "OPC": "opc"
}
RespCodes = {
    'SUCCESS': 200,
    'CONNECTION_FAILED': 11001,
    'CONNECTION_INVALID': 11002,
    'SUBSCRIPTION_FAILED': 11011,
    'UNSUBSCRIPTION_FAILED': 11012,
    'SNAPSHOT_FAILED': 11013,
    'CHANNELP_FAILED': 11031,
    'CHANNELR_FAILED': 11032
}


def DataType(c, d):
    return {"name": c, "type": d}


def enable_log(a):
    global HSD_Flag
    HSD_Flag = a


TopicTypes = {
    "SCRIP": "sf",
    "INDEX": "if",
    "DEPTH": "dp"
}
INDEX_INDEX = {
    "LTP": 2,
    "CLOSE": 3,
    "CHANGE": 10,
    "PERCHANGE": 11,
    "MULTIPLIER": 8,
    "PRECISION": 9
}
SCRIP_INDEX = {
    "VOLUME": 4,
    "LTP": 5,
    "CLOSE": 21,
    "VWAP": 13,
    "MULTIPLIER": 23,
    "PRECISION": 24,
    "CHANGE": 25,
    "PERCHANGE": 26,
    "TURNOVER": 27
}
Keys = {
    "TYPE": "type",
    "USER_ID": "user",
    "SESSION_ID": "sessionid",
    "SCRIPS": "scrips",
    "CHANNEL_NUM": "channelnum",
    "CHANNEL_NUMS": "channelnums",
    "JWT": "jwt",
    "REDIS_KEY": "redis",
    "STK_PRC": "stkprc",
    "HIGH_STK": "highstk",
    "LOW_STK": "lowstk",
    "OPC_KEY": "key",
    "AUTHORIZATION": "Authorization",
    "SID": "Sid",
    "X_ACCESS_TOKEN": "x-access-token",
    "SOURCE": "source"
}
ReqTypeValues = {
    "CONNECTION": "cn",
    "SCRIP_SUBS": "mws",
    "SCRIP_UNSUBS": "mwu",
    "INDEX_SUBS": "ifs",
    "INDEX_UNSUBS": "ifu",
    "DEPTH_SUBS": "dps",
    "DEPTH_UNSUBS": "dpu",
    "CHANNEL_RESUME": "cr",
    "CHANNEL_PAUSE": "cp",
    "SNAP_MW": "mwsp",
    "SNAP_DP": "dpsp",
    "SNAP_IF": "ifsp",
    "OPC_SUBS": "opc",
    "THROTTLING_INTERVAL": "ti",
    "STR": "str",
    "FORCE_CONNECTION": "fcn",
    "LOG": "log"
}

INDEX_MAPPING = [None] * 55
INDEX_MAPPING[0] = DataType("ftm0", FieldTypes.get("DATE"))
INDEX_MAPPING[1] = DataType("dtm1", FieldTypes.get("DATE"))
INDEX_MAPPING[INDEX_INDEX["LTP"]] = DataType("iv", FieldTypes.get("FLOAT32"))
INDEX_MAPPING[INDEX_INDEX["CLOSE"]] = DataType("ic", FieldTypes.get("FLOAT32"))
INDEX_MAPPING[4] = DataType("tvalue", FieldTypes.get("DATE"))
INDEX_MAPPING[5] = DataType("highPrice", FieldTypes.get("FLOAT32"))
INDEX_MAPPING[6] = DataType("lowPrice", FieldTypes.get("FLOAT32"))
INDEX_MAPPING[7] = DataType("openingPrice", FieldTypes.get("FLOAT32"))
INDEX_MAPPING.append(DataType("mul", FieldTypes.get("LONG")))
INDEX_MAPPING[INDEX_INDEX["PRECISION"]] = DataType("prec", FieldTypes.get("LONG"))
INDEX_MAPPING[INDEX_INDEX["CHANGE"]] = DataType("cng", FieldTypes.get("FLOAT32"))
INDEX_MAPPING[INDEX_INDEX["PERCHANGE"]] = DataType("nc", FieldTypes.get("STRING"))
INDEX_MAPPING[STRING_INDEX["NAME"]] = DataType("name", FieldTypes.get("STRING"))
INDEX_MAPPING[STRING_INDEX["SYMBOL"]] = DataType("tk", FieldTypes.get("STRING"))
INDEX_MAPPING[STRING_INDEX["EXCHG"]] = DataType("e", FieldTypes.get("STRING"))
INDEX_MAPPING[STRING_INDEX["TSYMBOL"]] = DataType("ts", FieldTypes.get("STRING"))

SCRIP_MAPPING = [None] * 100
SCRIP_MAPPING[0] = DataType("ftm0", FieldTypes["DATE"])
SCRIP_MAPPING[1] = DataType("dtm1", FieldTypes["DATE"])
SCRIP_MAPPING[2] = DataType("fdtm", FieldTypes["DATE"])
SCRIP_MAPPING[3] = DataType("ltt", FieldTypes["DATE"])
SCRIP_MAPPING[SCRIP_INDEX["VOLUME"]] = DataType("v", FieldTypes["LONG"])
SCRIP_MAPPING[SCRIP_INDEX["LTP"]] = DataType("ltp", FieldTypes["FLOAT32"])
SCRIP_MAPPING[6] = DataType("ltq", FieldTypes["LONG"])
SCRIP_MAPPING[7] = DataType("tbq", FieldTypes["LONG"])
SCRIP_MAPPING[8] = DataType("tsq", FieldTypes["LONG"])
SCRIP_MAPPING[9] = DataType("bp", FieldTypes["FLOAT32"])
SCRIP_MAPPING[10] = DataType("sp", FieldTypes["FLOAT32"])
SCRIP_MAPPING[11] = DataType("bq", FieldTypes["LONG"])
SCRIP_MAPPING[12] = DataType("bs", FieldTypes["LONG"])
SCRIP_MAPPING[SCRIP_INDEX["VWAP"]] = DataType("ap", FieldTypes["FLOAT32"])
SCRIP_MAPPING[14] = DataType("lo", FieldTypes["FLOAT32"])
SCRIP_MAPPING[15] = DataType("h", FieldTypes["FLOAT32"])
SCRIP_MAPPING[16] = DataType("lcl", FieldTypes["FLOAT32"])
SCRIP_MAPPING[17] = DataType("ucl", FieldTypes["FLOAT32"])
SCRIP_MAPPING[18] = DataType("yh", FieldTypes["FLOAT32"])
SCRIP_MAPPING[19] = DataType("yl", FieldTypes["FLOAT32"])
SCRIP_MAPPING[20] = DataType("op", FieldTypes["FLOAT32"])
SCRIP_MAPPING[SCRIP_INDEX["CLOSE"]] = DataType("c", FieldTypes["FLOAT32"])
SCRIP_MAPPING[22] = DataType("oi", FieldTypes["LONG"])
SCRIP_MAPPING[SCRIP_INDEX["MULTIPLIER"]] = DataType("mul", FieldTypes["LONG"])
SCRIP_MAPPING[SCRIP_INDEX["PRECISION"]] = DataType("prec", FieldTypes["LONG"])
SCRIP_MAPPING[SCRIP_INDEX["CHANGE"]] = DataType("cng", FieldTypes["FLOAT32"])
SCRIP_MAPPING[SCRIP_INDEX["PERCHANGE"]] = DataType("nc", FieldTypes["STRING"])
SCRIP_MAPPING[SCRIP_INDEX["TURNOVER"]] = DataType("to", FieldTypes["FLOAT32"])
SCRIP_MAPPING[STRING_INDEX["NAME"]] = DataType("name", FieldTypes["STRING"])
SCRIP_MAPPING[STRING_INDEX["SYMBOL"]] = DataType("tk", FieldTypes["STRING"])
SCRIP_MAPPING[STRING_INDEX["EXCHG"]] = DataType("e", FieldTypes["STRING"])
SCRIP_MAPPING[STRING_INDEX["TSYMBOL"]] = DataType("ts", FieldTypes["STRING"])

DEPTH_MAPPING = [None] * 55
DEPTH_MAPPING[0] = (DataType("ftm0", FieldTypes.get("DATE")))
DEPTH_MAPPING[1] = (DataType("dtm1", FieldTypes.get("DATE")))
DEPTH_MAPPING[2] = (DataType("bp", FieldTypes.get("FLOAT32")))
DEPTH_MAPPING[3] = (DataType("bp1", FieldTypes.get("FLOAT32")))
DEPTH_MAPPING[4] = (DataType("bp2", FieldTypes.get("FLOAT32")))
DEPTH_MAPPING[5] = (DataType("bp3", FieldTypes.get("FLOAT32")))
DEPTH_MAPPING[6] = (DataType("bp4", FieldTypes.get("FLOAT32")))
DEPTH_MAPPING[7] = (DataType("sp", FieldTypes.get("FLOAT32")))
DEPTH_MAPPING[8] = (DataType("sp1", FieldTypes.get("FLOAT32")))
DEPTH_MAPPING[9] = (DataType("sp2", FieldTypes.get("FLOAT32")))
DEPTH_MAPPING[10] = (DataType("sp3", FieldTypes.get("FLOAT32")))
DEPTH_MAPPING[11] = (DataType("sp4", FieldTypes.get("FLOAT32")))
DEPTH_MAPPING[12] = (DataType("bq", FieldTypes.get("LONG")))
DEPTH_MAPPING[13] = (DataType("bq1", FieldTypes.get("LONG")))
DEPTH_MAPPING[14] = (DataType("bq2", FieldTypes.get("LONG")))
DEPTH_MAPPING[15] = (DataType("bq3", FieldTypes.get("LONG")))
DEPTH_MAPPING[16] = (DataType("bq4", FieldTypes.get("LONG")))
DEPTH_MAPPING[17] = (DataType("bs", FieldTypes.get("LONG")))
DEPTH_MAPPING[18] = (DataType("bs1", FieldTypes.get("LONG")))
DEPTH_MAPPING[19] = (DataType("bs2", FieldTypes.get("LONG")))
DEPTH_MAPPING[20] = (DataType("bs3", FieldTypes.get("LONG")))
DEPTH_MAPPING[21] = (DataType("bs4", FieldTypes.get("LONG")))
DEPTH_MAPPING[22] = (DataType("bno1", FieldTypes.get("LONG")))
DEPTH_MAPPING[23] = (DataType("bno2", FieldTypes.get("LONG")))
DEPTH_MAPPING[24] = (DataType("bno3", FieldTypes.get("LONG")))
DEPTH_MAPPING[25] = (DataType("bno4", FieldTypes.get("LONG")))
DEPTH_MAPPING[26] = (DataType("bno5", FieldTypes.get("LONG")))
DEPTH_MAPPING[27] = (DataType("sno1", FieldTypes.get("LONG")))
DEPTH_MAPPING[28] = (DataType("sno2", FieldTypes.get("LONG")))
DEPTH_MAPPING[29] = (DataType("sno3", FieldTypes.get("LONG")))
DEPTH_MAPPING[30] = (DataType("sno4", FieldTypes.get("LONG")))
DEPTH_MAPPING[31] = (DataType("sno5", FieldTypes.get("LONG")))
DEPTH_MAPPING[DEPTH_INDEX["MULTIPLIER"]] = DataType("mul", FieldTypes["LONG"])
DEPTH_MAPPING[DEPTH_INDEX["PRECISION"]] = DataType("prec", FieldTypes["LONG"])
DEPTH_MAPPING[STRING_INDEX["NAME"]] = DataType("name", FieldTypes["STRING"])
DEPTH_MAPPING[STRING_INDEX["SYMBOL"]] = DataType("tk", FieldTypes["STRING"])
DEPTH_MAPPING[STRING_INDEX["EXCHG"]] = DataType("e", FieldTypes["STRING"])
DEPTH_MAPPING[STRING_INDEX["TSYMBOL"]] = DataType("ts", FieldTypes["STRING"])


def leadingZero(a):
    return "0" + str(a) if a < 10 else str(a)


def getFormatDate(a):
    date = datetime.datetime.fromtimestamp(a)
    formatDate = "{}/{}/{} {}:{}:{}".format(
        leadingZero(date.day),
        leadingZero(date.month),
        date.year,
        leadingZero(date.hour),
        leadingZero(date.minute),
        leadingZero(date.second)
    )
    return formatDate


class ByteData:
    def __init__(self, c):
        self.pos = 0
        self.bytes = [0] * (c)
        self.startOfMsg = 0

    def lenth(self):
        # logger.info(f"lenght of the bytes {self.bytes} {len(self.bytes)}")
        pass

    def markStartOfMsg(self):
        self.startOfMsg = self.pos
        self.pos += 2

    def markEndOfMsg(self):
        len = (self.pos - self.startOfMsg - 2)
        self.bytes[0] = ((len >> 8) & 255)
        self.bytes[1] = (len & 255)

    def clear(self):
        self.pos = 0

    def getPosition(self):
        return self.pos

    def getBytes(self):
        return self.bytes

    def appendByte(self, d):
        # logger.info(f"in append Bytes POS {self.pos}")
        # logger.info(f"in append Bytes d {d}")
        self.bytes[self.pos] = d
        self.pos += 1
        # logger.info(f"in append Bytes {self.bytes}")

    def appendByteAtPos(self, e, d):
        self.bytes[e] = d

    def appendChar(self, d):
        self.bytes[self.pos] = d
        self.pos += 1

    def appendCharAtPos(self, e, d):
        self.bytes[e] = d

    def appendShort(self, d):
        self.bytes[self.pos] = ((d >> 8) & 255)
        self.pos += 1
        self.bytes[self.pos] = (d & 255)
        self.pos += 1

    def appendInt(self, d):
        self.bytes[self.pos] = ((d >> 24) & 255)
        self.pos += 1
        self.bytes[self.pos] = ((d >> 16) & 255)
        self.pos += 1
        self.bytes[self.pos] = ((d >> 8) & 255)
        self.pos += 1
        self.bytes[self.pos] = (d & 255)
        self.pos += 1

    def appendLong(self, d):
        self.bytes[self.pos] = ((d >> 56) & 255)
        self.pos += 1
        self.bytes[self.pos] = ((d >> 48) & 255)
        self.pos += 1
        self.bytes[self.pos] = ((d >> 40) & 255)
        self.pos += 1
        self.bytes[self.pos] = ((d >> 32) & 255)
        self.pos += 1
        self.bytes[self.pos] = ((d >> 24) & 255)
        self.pos += 1
        self.bytes[self.pos] = ((d >> 16) & 255)
        self.pos += 1
        self.bytes[self.pos] = ((d >> 8) & 255)
        self.pos += 1
        self.bytes[self.pos] = (d & 255)
        self.pos += 1

    def append_long_as_big_int(self, e):
        d = int(e)
        self.bytes.append((d >> 56) & 255)
        self.bytes.append((d >> 48) & 255)
        self.bytes.append((d >> 40) & 255)
        self.bytes.append((d >> 32) & 255)
        self.bytes.append((d >> 24) & 255)
        self.bytes.append((d >> 16) & 255)
        self.bytes.append((d >> 8) & 255)
        self.bytes.append(d & 255)

    def append_string(self, d):
        str_len = len(d)
        for i in range(str_len):
            self.bytes[self.pos] = ord(d[i])
            self.pos += 1
            # self.bytes.append(ord(d[i]))

    def append_byte_array(self, d):
        byte_len = len(d)
        for i in range(byte_len):
            self.bytes[self.pos] = d[i]
            self.pos += 1
            # self.bytes.append(d[i])

    def appendByteArr(self, e, d):
        for i in range(d):
            self.bytes[self.pos] = e[i]
            self.pos += 1


class TopicData:
    def __init__(self, feed_type):
        self.feedType = feed_type
        self.exchange = None
        self.symbol = None
        self.tSymbol = None
        self.multiplier = 1
        self.precision = 2
        self.precisionValue = 100
        self.jsonArray = None
        self.fieldDataArray = [None] * 100
        self.updatedFieldsArray = [None] * 100
        self.fieldDataArray[STRING_INDEX["NAME"]] = feed_type

    def getKey(self):
        return f"{self.exchange}|{self.symbol}"

    def setLongValues(self, index_val, value):
        if self.fieldDataArray[index_val] != value and value != TRASH_VAL:
            self.fieldDataArray[index_val] = value
            self.updatedFieldsArray[index_val] = True

    def prepareCommonData(self):
        self.updatedFieldsArray[STRING_INDEX["NAME"]] = True
        self.updatedFieldsArray[STRING_INDEX["EXCHG"]] = True
        self.updatedFieldsArray[STRING_INDEX["SYMBOL"]] = True

    def setStringValues(self, e, d):
        if e == STRING_INDEX["SYMBOL"]:
            self.symbol = d
            self.fieldDataArray[STRING_INDEX["SYMBOL"]] = d
        elif e == STRING_INDEX["EXCHG"]:
            self.exchange = d
            self.fieldDataArray[STRING_INDEX["EXCHG"]] = d
        elif e == STRING_INDEX["TSYMBOL"]:
            self.tSymbol = d
            self.fieldDataArray[STRING_INDEX["TSYMBOL"]] = d
            self.updatedFieldsArray[STRING_INDEX["TSYMBOL"]] = True


class DepthTopicData(TopicData):
    def __init__(self):
        # logger.info("INSIDE DepthTopicData")
        super().__init__(TopicTypes["DEPTH"])
        self.updatedFieldsArray = [None] * 100
        self.multiplier = None
        self.precision = None
        self.precisionValue = None

    def setMultiplierAndPrec(self):
        # logger.info("INTO setMultiplierAndPrec")
        if self.updatedFieldsArray[DEPTH_INDEX['PRECISION']]:
            self.precision = self.fieldDataArray[DEPTH_INDEX['PRECISION']]
            self.precisionValue = 10 ** self.precision
        if self.updatedFieldsArray[DEPTH_INDEX['MULTIPLIER']]:
            self.multiplier = self.fieldDataArray[DEPTH_INDEX['MULTIPLIER']]

    def prepareData(self):
        # logger.info("INSIDE prepareData")
        self.prepareCommonData()
        # logger.info(f"\nDepth: {self.feedType} {self.exchange} {self.symbol}")
        json_res = {}
        for d in range(len(DEPTH_MAPPING)):
            c = DEPTH_MAPPING[d]
            e = self.fieldDataArray[d]
            if self.updatedFieldsArray[d] and e is not None and c:
                if c["type"] == FieldTypes.get("FLOAT32"):
                    e = round(e / (self.multiplier * self.precisionValue), self.precision)
                elif c["type"] == FieldTypes.get("DATE"):
                    e = getFormatDate(e)
                # logger.info(f"{d} : {c['name']} : {e}")
                json_res[c["name"]] = str(e)
        self.updatedFieldsArray = [None] * 100
        # logger.info(f"INSIDE Parse Data {json_res}")
        return json_res


def get_acknowledgement_req(a):
    buffer = ByteData(11) #bytearray(11)
    buffer.markStartOfMsg()
    buffer.appendByte(BinRespTypes["ACK_TYPE"])
    buffer.appendByte(1)
    buffer.appendByte(1)
    buffer.appendShort(4)
    buffer.appendInt(a)
    buffer.markEndOfMsg()
    return buffer.getBytes()


def prepare_connection_request(a):
    user_id_len = len(a)
    src = "JS_API"
    src_len = len(src)
    buffer = bytearray(user_id_len + src_len + 10)
    buffer[0] = BinRespTypes.get("CONNECTION_TYPE")
    buffer[1] = 2
    buffer[2] = 1
    buffer[3:5] = int(user_id_len).to_bytes(2, byteorder='big')
    buffer[5:5 + user_id_len] = a.encode()
    buffer[5 + user_id_len] = 2
    buffer[6 + user_id_len:8 + user_id_len] = int(src_len).to_bytes(2, byteorder='big')
    buffer[8 + user_id_len:8 + user_id_len + src_len] = src.encode()
    buffer[8 + user_id_len + src_len] = BinRespTypes.get("END_OF_MSG")
    return buffer


def prepareConnectionRequest2(a, c):
    # a = bytearray(bytes(a, encoding='utf8'))
    # c = bytearray(bytes(c, encoding='utf8'))
    src = "JS_API"
    # src = bytearray(bytes(src, encoding='utf8'))
    srcLen = len(src)
    jwtLen = len(a)
    redisLen = len(c)
    buffer = ByteData(srcLen + jwtLen + redisLen + 13)
    buffer.markStartOfMsg()
    buffer.appendByte(BinRespTypes["CONNECTION_TYPE"])
    buffer.appendByte(3)
    buffer.appendByte(1)
    buffer.appendShort(jwtLen)
    buffer.append_string(a)
    buffer.appendByte(2)
    buffer.appendShort(redisLen)
    buffer.append_string(c)
    buffer.appendByte(3)
    buffer.appendShort(srcLen)
    buffer.append_string(src)
    buffer.markEndOfMsg()
    return buffer.getBytes()


def is_scrip_ok(a):
    scrips_count = len(a.split("&"))
    if scrips_count > MAX_SCRIPS:
        logger.info(f"Maximum scrips allowed per request is {str(MAX_SCRIPS)}")
        return False
    return True


def getScripByteArray(c, a):
    if c[-1] == "&":
        c = c[:-1]
    scripArray = c.split("&")
    scripsCount = len(scripArray)
    dataLen = 0
    for index in range(scripsCount):
        scripArray[index] = a + "|" + scripArray[index]
        dataLen += len(scripArray[index]) + 1
    # logger.info(f"Data len {dataLen}")
    bytes = [0] * (dataLen + 2)
    pos = 0
    bytes[pos] = (scripsCount >> 8) & 255
    pos += 1
    bytes[pos] = scripsCount & 255
    pos += 1
    for index in range(scripsCount):
        currScrip = scripArray[index]
        scripLen = len(currScrip)
        bytes[pos] = scripLen & 255
        pos += 1
        for strIndex in range(scripLen):
            bytes[pos] = ord(currScrip[strIndex])
            pos += 1
    # logger.info(f"Bytes {bytes}")
    return bytes


def prepareSubsUnSubsRequest(scrips, subscribe_type, scrip_prefix, channel_num):
    # logger.info("Prepare prepareSubsUnSubsRequest")
    if not is_scrip_ok(scrips):
        return

    dataArr = getScripByteArray(scrips, scrip_prefix)
    # logger.info(f"Length Arr {dataArr}")
    # buffer = [0] * (len(dataArr) + 11) #ByteData(len(dataArr) + 11)
    buffer = ByteData(len(dataArr) + 11)
    buffer.markStartOfMsg()
    buffer.appendByte(subscribe_type)
    buffer.appendByte(2)
    buffer.appendByte(1)
    buffer.appendShort(len(dataArr))
    buffer.appendByteArr(dataArr, len(dataArr))
    buffer.appendByte(2)
    buffer.appendShort(1)
    buffer.appendByte(int(channel_num))
    buffer.markEndOfMsg()
    return buffer.getBytes()


def prepareSnapshotRequest(a, c, d):
    # logger.info(f"INTO prepareSnapshotRequest {a} {c} {d}")
    if not is_scrip_ok(a):
        return
    dataArr = getScripByteArray(a, d)
    # logger.info(f"DATA ARRAY {dataArr}")
    buffer = ByteData(len(dataArr) + 7)
    buffer.markStartOfMsg()
    buffer.appendByte(c)
    buffer.appendByte(1)
    buffer.appendByte(2)
    buffer.appendShort(len(dataArr))
    buffer.appendByteArr(dataArr, len(dataArr))
    buffer.markEndOfMsg()
    return buffer.getBytes()


def prepareChannelRequest(c, a):
    buffer = bytearray(15)
    buffer[0] = c
    buffer[1] = 1
    buffer[2] = 1
    buffer[3:5] = (8).to_bytes(2, byteorder='big')
    int1, int2 = 0, 0
    for d in a:
        if 0 < d <= 32:
            int1 |= 1 << d
        elif 32 < d <= 64:
            int2 |= 1 << d
        else:
            logger.info("Error: Channel values must be in this range  [ val > 0 && val < 65 ]")
    buffer[5:9] = int2.to_bytes(4, byteorder='big')
    buffer[9:13] = int1.to_bytes(4, byteorder='big')
    return buffer


def prepareThrottlingIntervalRequest(a):
    buffer = bytearray(11)
    buffer[0] = BinRespTypes.get("THROTTLING_TYPE")
    buffer[1] = 1
    buffer[2] = 1
    buffer[3] = (4 >> 8) & 255
    buffer[4] = 4 & 255
    buffer[5] = (a >> 24) & 255
    buffer[6] = (a >> 16) & 255
    buffer[7] = (a >> 8) & 255
    buffer[8] = a & 255
    return buffer


def get_scrip_byte_array(c, a):
    if c[-1] == "&":
        c = c[:-1]
    scrip_array = c.split("&")
    scrips_count = len(scrip_array)
    data_len = 0
    for index in range(scrips_count):
        scrip_array[index] = a + "|" + scrip_array[index]
        data_len += len(scrip_array[index]) + 1
    bytes = bytearray(data_len + 2)
    pos = 0
    bytes[pos] = (scrips_count >> 8) & 255
    pos += 1
    bytes[pos] = scrips_count & 255
    pos += 1
    for index in range(scrips_count):
        curr_scrip = scrip_array[index]
        scrip_len = len(curr_scrip)
        bytes[pos] = scrip_len & 255
        pos += 1
        for str_index in range(scrip_len):
            bytes[pos] = ord(curr_scrip[str_index])
            pos += 1
    return bytes


def get_opc_chain_subs_request(d, e, a, c, f):
    opc_key_len = len(d)
    buffer = bytearray(opc_key_len + 30)
    pos = 0
    buffer[pos] = BinRespTypes.get("OPC_SUBSCRIBE")
    pos += 1
    buffer[pos] = 5
    pos += 1
    buffer[pos] = 1
    pos += 1
    buffer[pos] = opc_key_len >> 8 & 255
    pos += 1
    buffer[pos] = opc_key_len & 255
    pos += 1
    for i in range(opc_key_len):
        buffer[pos] = ord(d[i])
        pos += 1
    buffer[pos] = 2
    pos += 1
    buffer[pos] = 8 >> 8 & 255
    pos += 1
    buffer[pos] = 8 & 255
    pos += 1
    # The below code assumes the input value of e is a 64-bit integer
    buffer[pos] = e >> 56 & 255
    pos += 1
    buffer[pos] = e >> 48 & 255
    pos += 1
    buffer[pos] = e >> 40 & 255
    pos += 1
    buffer[pos] = e >> 32 & 255
    pos += 1
    buffer[pos] = e >> 24 & 255
    pos += 1
    buffer[pos] = e >> 16 & 255
    pos += 1
    buffer[pos] = e >> 8 & 255
    pos += 1
    buffer[pos] = e & 255
    pos += 1
    buffer[pos] = 3
    pos += 1
    buffer[pos] = 1 >> 8 & 255
    pos += 1
    buffer[pos] = 1 & 255
    pos += 1
    buffer[pos] = a
    pos += 1
    buffer[pos] = 4
    pos += 1
    buffer[pos] = 1 >> 8 & 255
    pos += 1
    buffer[pos] = 1 & 255
    pos += 1
    buffer[pos] = c
    pos += 1
    buffer[pos] = 5
    pos += 1
    buffer[pos] = 1 >> 8 & 255
    pos += 1
    buffer[pos] = 1 & 255
    pos += 1
    buffer[pos] = f
    return buffer


def send_json_arr_resp(a):
    json_arr_res = []
    json_arr_res.append(a)
    return json.dumps(json_arr_res)


def buf2long(a):
    b = bytearray(a)
    val = 0
    leng = len(b)
    for i in range(leng):
        j = leng - 1 - i
        val += b[j] << (i * 8)
    return val


def buf2string(a):
    import numpy as np
    return ''.join(map(chr, np.frombuffer(a, dtype=np.uint8)))


class ScripTopicData(TopicData):
    def __init__(self):
        super().__init__(TopicTypes["SCRIP"])
        # logger.info("After topic")
        self.precision = None
        self.precisionValue = None
        self.multiplier = None

    def setMultiplierAndPrec(self):
        if self.updatedFieldsArray[SCRIP_INDEX["PRECISION"]]:
            self.precision = self.fieldDataArray[SCRIP_INDEX["PRECISION"]]
            self.precisionValue = pow(10, self.precision)
        if self.updatedFieldsArray[SCRIP_INDEX["MULTIPLIER"]]:
            self.multiplier = self.fieldDataArray[SCRIP_INDEX["MULTIPLIER"]]

    def prepareData(self):
        self.prepareCommonData()
        if self.updatedFieldsArray[SCRIP_INDEX["LTP"]] or self.updatedFieldsArray[SCRIP_INDEX["CLOSE"]]:
            ltp = self.fieldDataArray[SCRIP_INDEX["LTP"]]
            close = self.fieldDataArray[SCRIP_INDEX["CLOSE"]]
            if ltp is not None and close is not None:
                change = ltp - close
                self.fieldDataArray[SCRIP_INDEX["CHANGE"]] = change
                self.updatedFieldsArray[SCRIP_INDEX["CHANGE"]] = True
                self.fieldDataArray[SCRIP_INDEX["PERCHANGE"]] = "{:.2f}".format((change / close * 100))
                self.updatedFieldsArray[SCRIP_INDEX["PERCHANGE"]] = True
        if self.updatedFieldsArray[SCRIP_INDEX["VOLUME"]] or self.updatedFieldsArray[SCRIP_INDEX["VWAP"]]:
            volume = self.fieldDataArray[SCRIP_INDEX["VOLUME"]]
            vwap = self.fieldDataArray[SCRIP_INDEX["VWAP"]]
            if volume is not None and vwap is not None:
                self.fieldDataArray[SCRIP_INDEX["TURNOVER"]] = volume * vwap
                self.updatedFieldsArray[SCRIP_INDEX["TURNOVER"]] = True
        # logger.info(f"\nScrip::{self.feedType}|{self.exchange}|{self.symbol}")
        jsonRes = {}
        for index in range(len(SCRIP_MAPPING)):
            dataType = SCRIP_MAPPING[index]
            val = self.fieldDataArray[index]
            if self.updatedFieldsArray[index] and val is not None and dataType:
                if dataType["type"] == FieldTypes["FLOAT32"]:
                    val = "{:.2f}".format(val / (self.multiplier * self.precisionValue))
                elif dataType["type"] == FieldTypes["DATE"]:
                    val = getFormatDate(val)
                # logger.info(f'{str(index)}:{dataType["name"]}:{str(val)}')
                jsonRes[dataType["name"]] = str(val)
        self.updatedFieldsArray = [None] * 100
        return jsonRes


class IndexTopicData(TopicData):
    def __init__(self):
        # logger.info("INSIDE IndexTopicData")
        super().__init__(TopicTypes["INDEX"])
        self.updatedFieldsArray = [None] * 100
        self.multiplier = None
        self.precision = None
        self.precisionValue = None

    def setMultiplierAndPrec(self):
        if self.updatedFieldsArray[INDEX_INDEX["PRECISION"]]:
            self.precision = self.fieldDataArray[INDEX_INDEX["PRECISION"]]
            self.precisionValue = 10 ** self.precision
        if self.updatedFieldsArray[INDEX_INDEX["MULTIPLIER"]]:
            self.multiplier = self.fieldDataArray[INDEX_INDEX["MULTIPLIER"]]

    def prepareData(self):
        self.prepareCommonData()
        if self.updatedFieldsArray[INDEX_INDEX["LTP"]] or self.updatedFieldsArray[INDEX_INDEX["CLOSE"]]:
            ltp = self.fieldDataArray[INDEX_INDEX["LTP"]]
            close = self.fieldDataArray[INDEX_INDEX["CLOSE"]]
            if ltp is not None and close is not None:
                change = ltp - close
                self.fieldDataArray[INDEX_INDEX["CHANGE"]] = change
                self.updatedFieldsArray[INDEX_INDEX["CHANGE"]] = True
                per_change = round(change / close * 100, self.precision)
                self.fieldDataArray[INDEX_INDEX["PERCHANGE"]] = per_change
                self.updatedFieldsArray[INDEX_INDEX["PERCHANGE"]] = True
        # logger.info(f"\nIndex::{self.feedType}|{self.exchange}|{self.symbol}")
        json_res = {}
        for index in range(len(INDEX_MAPPING)):
            data_type = INDEX_MAPPING[index]
            val = self.fieldDataArray[index]
            if self.updatedFieldsArray[index] and val is not None and data_type is not None:
                if data_type["type"] == FieldTypes["FLOAT32"]:
                    val = round(val / (self.multiplier * self.precisionValue), self.precision)
                elif data_type["type"] == FieldTypes["DATE"]:
                    val = getFormatDate(val)
                # logger.info(f'{str(index)}:{data_type["name"]}:{str(val)}')
                json_res[data_type["name"]] = str(val)
        self.updatedFieldsArray = [None] * 100
        return json_res


class HSWrapper:
    def __init__(self):
        self.counter = 0
        self.ack_num = 0

    def getNewTopicData(self, c):
        # logger.info(f"INPUT {c}")
        feed_type, *_ = c.split("|")
        topic = None
        if feed_type == TopicTypes.get("SCRIP"):
            topic = ScripTopicData()
        elif feed_type == TopicTypes.get("INDEX"):
            # logger.info("INTO FEED TYPE index")
            topic = IndexTopicData()
        elif feed_type == TopicTypes.get("DEPTH"):
            topic = DepthTopicData()
        return topic

    def getStatus(self, c, d):
        status = BinRespStat.get("NOT_OK")
        field_count = buf2long(c[d:d + 1])
        d += 1
        if field_count > 0:
            fld = buf2long(c[d:d + 1])
            d = d + 1
            field_length = buf2long(c[d:d + 2])
            d += 2
            status = buf2string(c[d:d + field_length])
            d += field_length
        return status

    def parseData(self, e):
        pos = 0
        # logger.info(f"INTO Parse Data {e}")
        packetsCount = buf2long(e[pos:2])
        pos += 2
        type = int.from_bytes(e[pos:pos + 1], 'big')
        pos += 1
        # logger.info(f"Type in HSWebsocket {type}")
        # logger.info(f"parse data {e}")
        # logger.info(f"parse data len {len(e)}")
        if type == BinRespTypes.get("CONNECTION_TYPE"):
            jsonRes = {}
            fCount = int.from_bytes(e[pos:pos + 1], 'big')
            pos += 1
            if fCount >= 2:
                fid1 = int.from_bytes(e[pos:pos + 1], 'big')
                pos += 1
                valLen = int.from_bytes(e[pos:pos + 2], 'big')
                pos += 2
                status = e[pos:pos + valLen].decode('utf-8')
                pos += valLen
                fid1 = int.from_bytes(e[pos:pos + 1], 'big')
                pos += 1
                valLen = int.from_bytes(e[pos:pos + 2], 'big')
                pos += 2
                ackCount = int.from_bytes(e[pos:pos + valLen], 'big')
                # logger.info(f"STATUS {status}")
                if status == BinRespStat.get("OK"):
                    jsonRes['stat'] = STAT.get("OK")
                    jsonRes['type'] = RespTypeValues.get("CONN")
                    jsonRes['msg'] = "successful"
                    jsonRes['stCode'] = RespCodes.get("SUCCESS")
                elif status == BinRespStat.get("NOT_OK"):
                    jsonRes['stat'] = STAT.get("NOT_OK")
                    jsonRes['type'] = RespTypeValues.get("CONN")
                    jsonRes['msg'] = "failed"
                    jsonRes['stCode'] = RespCodes.get("CONNECTION_FAILED")
                self.ack_num = ackCount
            elif fCount == 1:
                fid1 = int.from_bytes(e[pos:pos + 1], 'big')
                pos += 1
                valLen = int.from_bytes(e[pos:pos + 2], 'big')
                pos += 2
                status = e[pos:pos + valLen].decode('utf-8')
                pos += valLen
                if status == BinRespStat.get("OK"):
                    jsonRes['stat'] = STAT.get("OK")
                    jsonRes['type'] = RespTypeValues.get("CONN")
                    jsonRes['msg'] = "successful"
                    jsonRes['stCode'] = RespCodes.get("SUCCESS")
                elif status == BinRespStat.get("NOT_OK"):
                    jsonRes['stat'] = STAT.get("NOT_OK")
                    jsonRes['type'] = RespTypeValues.get("CONN")
                    jsonRes['msg'] = "failed"
                    jsonRes['stCode'] = RespCodes.get("CONNECTION_FAILED")
            else:
                jsonRes['stat'] = STAT.get("NOT_OK")
                jsonRes['type'] = RespTypeValues.get("CONN")
                jsonRes['msg'] = "invalid field count"
                jsonRes['stCode'] = RespCodes.get("CONNECTION_INVALID")
            return send_json_arr_resp(jsonRes)
        else:
            if type == BinRespTypes.get("DATA_TYPE"):
                # logger.info("IN By Datatype ")
                # logger.info(f"IN By self.ack_num {self.ack_num}")
                msg_num = 0
                if self.ack_num > 0:
                    # logger.info(f"ack_num {self.ack_num}")
                    self.counter += 1
                    msg_num = buf2long(e[pos: pos + 4])
                    pos += 4
                    if self.counter == self.ack_num:
                        req = get_acknowledgement_req(msg_num)
                        if ws:
                            ws.send(req, 0x2)
                            self.counter = 0
                        # logger.info(f"Acknowledgement sent for message num: {msg_num}")
                h = []
                g = buf2long(e[pos: pos + 2])
                # logger.info(f"G in {g}")
                pos += 2
                for n in range(g):
                    pos += 2
                    c = buf2long(e[pos: pos + 1])
                    # logger.info(f"ResponseType: {c}")
                    pos += 1
                    if c == ResponseTypes.get("SNAP"):
                        f = buf2long(e[pos: pos + 4])
                        pos += 4
                        # logger.info(f"topic Id: {f}")
                        name_len = buf2long(e[pos: pos + 1])
                        pos += 1
                        topic_name = buf2string(e[pos: pos + name_len])
                        # logger.info(f"TOPIC Name {topic_name}")
                        pos += name_len
                        d = self.getNewTopicData(topic_name)
                        if d:
                            topic_list[f] = d
                            fcount = buf2long(e[pos: pos + 1])
                            pos += 1
                            # logger.info(f"fcount1: {fcount}")
                            for index in range(fcount):
                                fvalue = buf2long(e[pos: pos + 4])
                                d.setLongValues(index, fvalue)
                                pos += 4
                            # logger.info("Able to set ")
                            d.setMultiplierAndPrec()
                            fcount = buf2long(e[pos: pos + 1])
                            pos += 1
                            # logger.info(f"fcount2: {fcount}")
                            for index in range(fcount):
                                fid = buf2long(e[pos: pos + 1])
                                pos += 1
                                data_len = buf2long(e[pos: pos + 1])
                                pos += 1
                                str_val = buf2string(e[pos: pos + data_len])
                                pos += data_len
                                d.setStringValues(fid, str_val)
                                # logger.info(f"{fid} : {str_val}")
                            h.append(d.prepareData())
                        else:
                            logger.info("Invalid topic feed type !")
                    else:
                        if c == ResponseTypes.get("UPDATE"):
                            logger.info("updates ......")
                            f = buf2long(e[pos: pos + 4])
                            # logger.info(f"topic Id: {f}")
                            pos += 4
                            d = topic_list[f]
                            if not d:
                                logger.info("Topic Not Available in TopicList!")
                            else:
                                # logger.info("INSIDE Else COndition ")
                                fcount = buf2long(e[pos:pos + 1])
                                pos += 1
                                # logger.info(f"fcount1: {fcount}")
                                for index in range(fcount):
                                    fvalue = buf2long(e[pos:pos + 4])
                                    d.setLongValues(index, fvalue)
                                    # d[index] = fvalue
                                    # logger.info(f"index: {index} val: {fvalue}")
                                    pos += 4
                            h.append(d.prepareData())
                        else:
                            logger.info(f"Invalid ResponseType: {c}")
                return h
            else:
                if type == BinRespTypes.get("SUBSCRIBE_TYPE") or type == BinRespTypes.get("UNSUBSCRIBE_TYPE"):
                    # logger.info("INTO SUBScirbe Condition")
                    status = self.getStatus(e, pos)
                    json_res = {}
                    if status == BinRespStat.get("OK"):
                        json_res["stat"] = STAT.get("OK")
                        json_res[
                            "type"] = RespTypeValues.get("SUBS") if type == BinRespTypes.get(
                            "SUBSCRIBE_TYPE") else RespTypeValues.get("UNSUBS")
                        json_res["msg"] = "successful"
                        json_res["stCode"] = RespCodes.get("SUCCESS")
                    elif status == BinRespStat.get("NOT_OK"):
                        json_res["stat"] = STAT.get("NOT_OK")
                        if type == BinRespTypes.get("SUBSCRIBE_TYPE"):
                            json_res["type"] = RespTypeValues.get("SUBS")
                            json_res["msg"] = "subscription failed"
                            json_res["stCode"] = RespCodes.get("SUBSCRIPTION_FAILED")
                        else:
                            json_res["type"] = RespTypeValues.get("UNSUBS")
                            json_res["msg"] = "unsubscription failed"
                            json_res["stCode"] = RespCodes.get("UNSUBSCRIPTION_FAILED")
                    return send_json_arr_resp(json_res)

                else:
                    if type == BinRespTypes.get("SNAPSHOT"):
                        status = self.getStatus(e, pos)
                        json_res = {}
                        if status == BinRespStat.get("OK"):
                            json_res["stat"] = STAT.get("OK")
                            json_res["type"] = RespTypeValues.get("SNAP")
                            json_res["msg"] = "successful"
                            json_res["stCode"] = RespCodes.get("SUCCESS")
                        elif status == BinRespStat.get("NOT_OK"):
                            json_res["stat"] = STAT.get("NOT_OK")
                            json_res["type"] = RespTypeValues.get("SNAP")
                            json_res["msg"] = "failed"
                            json_res["stCode"] = RespCodes.get("SNAPSHOT_FAILED")
                        return send_json_arr_resp(json_res)
                    elif type == BinRespTypes.get("CHPAUSE_TYPE") or type == BinRespTypes.get("CHRESUME_TYPE"):
                        status = self.getStatus(e, pos)
                        json_res = {}
                        if status == BinRespStat.get("OK"):
                            json_res["stat"] = STAT.get("OK")
                            if type == BinRespTypes.get("CHPAUSE_TYPE"):
                                json_res["type"] = RespTypeValues.get("CHANNELP")
                            else:
                                json_res["type"] = RespTypeValues.get("CHANNELR")
                            json_res["msg"] = "successful"
                            json_res["stCode"] = RespCodes.get("SUCCESS")
                        elif status == BinRespStat.get("NOT_OK"):
                            json_res["stat"] = STAT.get("NOT_OK")
                            if type == BinRespTypes.get("CHPAUSE_TYPE"):
                                json_res["type"] = RespTypeValues.get("CHANNELP")
                            else:
                                json_res["type"] = RespTypeValues.get("CHANNELR")
                            json_res["msg"] = "failed"
                            if type == BinRespTypes.get("CHPAUSE_TYPE"):
                                json_res["stCode"] = RespCodes.get("CHANNELP_FAILED")
                            else:
                                json_res["stCode"] = RespCodes.get("CHANNELR_FAILED")
                        return send_json_arr_resp(json_res)
                    elif type == BinRespTypes.get("OPC_SUBSCRIBE"):
                        status = self.getStatus(e, pos)
                        pos += 5
                        json_res = {}
                        if status == BinRespStat.get("OK"):
                            json_res["stat"] = STAT.get("OK")
                            json_res["type"] = RespTypeValues.get("OPC")
                            json_res["msg"] = "successful"
                            json_res["stCode"] = RespCodes.get("SUCCESS")
                            fld = buf2long(e[pos: pos + 1])
                            pos += 1
                            field_length = buf2long(e[pos: pos + 2])
                            pos += 2
                            opc_key = buf2string(e[pos: pos + field_length])
                            pos += field_length
                            json_res["key"] = opc_key
                            fld = buf2long(e[pos: pos + 1])
                            pos += 1
                            field_length = buf2long(e[pos: pos + 2])
                            pos += 2
                            data = buf2string(e[pos:pos + field_length])
                            pos += field_length
                            json_res["scrips"] = json.loads(data)["data"]
                        elif status == BinRespStat.get("NOT_OK"):
                            json_res["stat"] = STAT.get("NOT_OK")
                            json_res["type"] = RespTypeValues.get("OPC")
                            json_res["msg"] = "failed"
                            json_res["stCode"] = 11040

                        return send_json_arr_resp(json_res)
                    else:
                        return None


class StartServer:
    def __init__(self, a, token, sid, onopen, onmessage, onerror, onclose):
        self.userSocket = self
        self.a = a
        self.onopen = onopen
        self.onmessage = onmessage
        self.onerror = onerror
        self.onclose = onclose
        self.token, self.sid = token, sid
        global ws
        try:
            # websocket.enableTrace(True)
            ws = websocket.WebSocketApp(a,
                                        on_open=self.on_open,
                                        on_message=self.on_message,
                                        on_error=self.on_error,
                                        on_close=self.on_close)
        except Exception:
            logger.info("WebSocket not supported!")

        if ws:
            # logger.info("WS is a array buffer ")
            self.hsWrapper = HSWrapper()
            # logger.info("HS WRAPPER IS DONE ")
        else:
            logger.info("WebSocket not initialized!")

        ws.run_forever()

    def on_open(self, ws):
        # logger.info("[OnOpen]: Function is running in HSWebscoket")
        self.onopen()

    def on_message(self, ws, inData):
        # logger.info("[OnMessage]: Function is running in HSWebsocket")
        outData = None
        if isinstance(inData, bytes):
            jsonData = self.hsWrapper.parseData(inData)
            # logger.info(f"JSON DATA in HSWEBSOCKE ON MESSAGE {jsonData}")
            if jsonData:
                outData = json.dumps(jsonData) if isEncyptOut else jsonData
        else:
            outData = inData if not isEncyptIn else json.loads(inData) if isEncyptOut else inData
        if outData:
            self.onmessage(outData)

    def on_close(self, ws, close_status_code, close_msg):
        # logger.info(f"[OnClose]: Function is running HSWebsocket {close_status_code}")
        self.onclose()

    def on_error(self, ws, error):
        self.onerror(error)
        logger.info(f"ERROR in HSWebscoket {error}")
        logger.info("[OnError]: Function is running HSWebsocket")


SCRIP_PREFIX = "sf"
INDEX_PREFIX = "if"
DEPTH_PREFIX = "dp"


def convert_to_dict(scrips=None, channelnum=None):
    dict_data = {"scrips": scrips, "sub_type": BinRespTypes.get("SUBSCRIBE_TYPE"), "SCRIP_PREFIX": SCRIP_PREFIX,
                 "channelnum": channelnum}
    return dict_data


class HSWebSocket:
    OPEN = 0
    readyState = 0

    def __init__(self):
        self.onclose = None
        self.url = None
        self.onopen = None
        self.onmessage = None
        self.on_error = None

    def open_connection(self, url, token, sid, on_open, on_message, on_error, on_close):
        self.url = url
        self.onopen = on_open
        self.onmessage = on_message
        self.on_error = on_error
        self.onclose = on_close
        StartServer(self.url, token, sid, self.onopen, self.onmessage, self.on_error, self.onclose)

    def hs_send(self, d):
        req_json = json.loads(d)
        req_type = req_json[Keys.get("TYPE")]
        # logger.info(f"Req Type {req_type}")
        req = {}
        if Keys.get("SCRIPS") in req_json:
            scrips = req_json[Keys.get("SCRIPS")]
            # logger.info(f"scrips {scrips}")
            channelnum = req_json[Keys.get("CHANNEL_NUM")]
            # logger.info(f"CHANNEL NUM {channelnum}")
        else:
            scrips = None
            channelnum = 1
        # scrips = None
        # channelnum = req_json[Keys.get("CHANNEL_NUM")]
        if req_type == ReqTypeValues.get("CONNECTION"):
            if Keys.get("USER_ID") in req_json:
                user = req_json[Keys.get("USER_ID")]
                req = prepare_connection_request(user)
            elif Keys.get("SESSION_ID") in req_json:
                # logger.info("INSIDE SESSION_ID")
                session_id = req_json[Keys.get("SESSION_ID")]
                req = prepare_connection_request(session_id)
            elif Keys.get("AUTHORIZATION") in req_json:
                # logger.info("INSIDE AUTHORIZATION")
                jwt = req_json[Keys.get("AUTHORIZATION")]
                redis_key = req_json[Keys.get("SID")]
                if jwt and redis_key:
                    req = prepareConnectionRequest2(jwt, redis_key)
                    # req = {"Authorization": jwt, "Sid": redis_key}
                else:
                    logger.info("Authorization mode is enabled: Authorization or Sid not found !")
            else:
                logger.info("Invalid conn mode !")
        elif req_type == ReqTypeValues.get("SCRIP_SUBS"):
            req = prepareSubsUnSubsRequest(scrips, BinRespTypes.get("SUBSCRIBE_TYPE"), SCRIP_PREFIX, channelnum)
            # logger.info(f"*********** SUB SCRIPS req {req}")
        elif req_type == ReqTypeValues.get("SCRIP_UNSUBS"):
            req = prepareSubsUnSubsRequest(scrips, BinRespTypes.get("UNSUBSCRIBE_TYPE"), SCRIP_PREFIX, channelnum)
        elif req_type == ReqTypeValues.get("INDEX_SUBS"):
            req = prepareSubsUnSubsRequest(scrips, BinRespTypes.get("SUBSCRIBE_TYPE"), INDEX_PREFIX, channelnum)
        elif req_type == ReqTypeValues.get("INDEX_UNSUBS"):
            req = prepareSubsUnSubsRequest(scrips, BinRespTypes.get("UNSUBSCRIBE_TYPE"), INDEX_PREFIX, channelnum)
        elif req_type == ReqTypeValues.get("DEPTH_SUBS"):
            req = prepareSubsUnSubsRequest(scrips, BinRespTypes.get("SUBSCRIBE_TYPE"), DEPTH_PREFIX, channelnum)
        elif req_type == ReqTypeValues.get("DEPTH_UNSUBS"):
            req = prepareSubsUnSubsRequest(scrips, BinRespTypes.get("UNSUBSCRIBE_TYPE"), DEPTH_PREFIX, channelnum)
        elif req_type == ReqTypeValues.get("CHANNEL_PAUSE"):
            req = prepareChannelRequest(BinRespTypes.get("CHPAUSE_TYPE"), channelnum)
        elif req_type == ReqTypeValues.get("CHANNEL_RESUME"):
            req = prepareChannelRequest(BinRespTypes.get("CHRESUME_TYPE"), channelnum)
        elif req_type == ReqTypeValues.get("SNAP_MW"):
            req = prepareSnapshotRequest(scrips, BinRespTypes.get("SNAPSHOT"), SCRIP_PREFIX)
        elif req_type == ReqTypeValues.get("SNAP_DP"):
            req = prepareSnapshotRequest(scrips, BinRespTypes.get("SNAPSHOT"), DEPTH_PREFIX)
        elif req_type == ReqTypeValues.get("SNAP_IF"):
            req = prepareSnapshotRequest(scrips, BinRespTypes.get("SNAPSHOT"), INDEX_PREFIX)
        elif req_type == ReqTypeValues.get("OPC_SUBS"):
            req = get_opc_chain_subs_request(req[Keys.get("OPC_KEY")], req[Keys.get("STK_PRC")],
                                             req[Keys.get("HIGH_STK")],
                                             req[Keys.get("LOW_STK")], channelnum)
        elif req_type == ReqTypeValues.get("THROTTLING_INTERVAL"):
            req = prepareThrottlingIntervalRequest(scrips)
        elif req_type == ReqTypeValues.get("LOG"):
            enable_log(req.get('enable'))
        if ws and req:
            ws.send(req, 0x2)
        else:
            logger.info("Unable to send request !, Reason: Connection faulty or request not valid !")

    def close(self):
        ws.close()


#
# import json
# import websocket
#
#
# class HSIWebSocket:
#     def __init__(self, url):
#         self.hsiSocket = None
#         self.reqData = None
#         self.hsiWs = None
#         self.OPEN = 0
#         self.readyState = 0
#         self.url = url
#         self.start_hsi_server(self.url)
#
#     def start_hsi_server(self, url):
#         self.hsiWs = websocket.WebSocketApp(url,
#                                             on_message=self.on_message,
#                                             on_error=self.on_error,
#                                             on_close=self.on_close)
#         self.hsiWs.on_open = self.on_open
#         self.hsiWs.run_forever()
#
#     def on_message(self, ws, message):
#         logger.info(f"Received message: {message}")
#
#     def on_error(self, ws, error):
#         logger.info(f"Error: {error}")
#
#     def on_close(self, ws):
#         logger.info("Connection closed")
#         self.OPEN = 0
#         self.readyState = 0
#         self.hsiWs = None
#
#     def on_open(self, ws):
#         logger.info("Connection established")
#         self.OPEN = 1
#         self.readyState = 1
#
#     def send(self, d):
#         reqJson = json.loads(d)
#         req = None
#         if reqJson['type'] == 'CONNECTION':
#             if 'Authorization' in reqJson and 'Sid' in reqJson and 'src' in reqJson:
#                 req = {
#                     'type': 'cn',
#                     'Authorization': reqJson['Authorization'],
#                     'Sid': reqJson['Sid'],
#                     'src': reqJson['src']
#                 }
#                 self.reqData = req
#             else:
#                 if 'x-access-token' in reqJson and 'src' in reqJson:
#                     req = {
#                         'type': 'cn',
#                         'x-access-token': reqJson['x-access-token'],
#                         'src': reqJson['src']
#                     }
#                     self.reqData = req
#                 else:
#                     logger.info("Invalid connection mode !")
#         else:
#             if reqJson['type'] == 'FORCE_CONNECTION':
#                 self.reqData = self.reqData['type'] = 'fcn'
#                 req = self.reqData
#             else:
#                 logger.info("Invalid Request !")
#         if self.hsiWs and req:
#             logger.info(f"REQ {req}")
#             self.hsiWs.send(json.dumps(req))
#         else:
#             logger.info("Unable to send request! Reason: Connection faulty or request not valid!")
#
#     def close(self):
#         self.hsiWs.close()
#         self.OPEN = 0
#         self.readyState = 0
#         self.hsiWs = None


class StartHSIServer:
    def __init__(self, url, onopen, onmessage, onerror, onclose):
        self.OPEN = None
        self.readyState = None
        self.url = url
        self.onopen = onopen
        self.onmessage = onmessage
        self.onerror = onerror
        self.onclose = onclose
        # self.token, self.sid = token, sid
        global hsiws
        try:
            # websocket.enableTrace(True)
            hsiws = websocket.WebSocketApp(self.url,
                                           on_open=self.on_open,
                                           on_message=self.on_message,
                                           on_error=self.on_error,
                                           on_close=self.on_close)
        except Exception:
            logger.info("WebSocket not supported!")
        hsiws.run_forever()

    def on_message(self, ws, message):
        # logger.info(f"Received message: {message}")
        self.onmessage(message)

    def on_error(self, ws, error):
        logger.info(f"Error: {error}")
        self.onerror(error)

    def on_close(self, ws, close_status_code, close_msg):
        logger.info("Connection closed")
        self.OPEN = 0
        self.readyState = 0
        hsiWs = None
        self.onclose()

    def on_open(self, ws):
        logger.info("Connection established HSWebSocket")
        self.OPEN = 1
        self.readyState = 1
        self.onopen()


class HSIWebSocket:
    def __init__(self):
        # self.hsiWs = None
        self.hsiSocket = None
        self.reqData = None
        self.OPEN = 0
        self.readyState = 0
        self.url = None
        self.onopen = None
        self.onmessage = None
        self.onclose = None
        self.onerror = None
        # self.token, self.sid = token, sid

    def open_connection(self, url, onopen, onmessage, onclose, onerror):
        self.url = url
        self.onopen = onopen
        self.onmessage = onmessage
        self.onclose = onclose
        self.onerror = onerror
        StartHSIServer(self.url, self.onopen, self.onmessage, self.onerror, self.onclose)

    def send(self, d):
        reqJson = json.loads(d)
        req = None
        if reqJson['type'] == 'CONNECTION':
            if 'Authorization' in reqJson and 'Sid' in reqJson and 'source' in reqJson:
                req = {
                    'type': 'cn',
                    'Authorization': reqJson['Authorization'],
                    'Sid': reqJson['Sid'],
                    'src': reqJson['source']
                }
                self.reqData = req
            else:
                if 'x-access-token' in reqJson and 'src' in reqJson:
                    req = {
                        'type': 'cn',
                        'x-access-token': reqJson['x-access-token'],
                        'source': reqJson['source']
                    }
                    self.reqData = req
                else:
                    logger.info("Invalid connection mode !")
        else:
            if reqJson['type'] == 'FORCE_CONNECTION':
                self.reqData = self.reqData['type'] = 'fcn'
                req = self.reqData
            else:
                logger.info("Invalid Request !")
        if hsiws and req:
            js_obj = json.dumps(req)
            hsiws.send(js_obj)
        else:
            logger.info("Unable to send request! Reason: Connection faulty or request not valid!")

    def close(self):
        self.OPEN = 0
        self.readyState = 0
        hsiws.close()