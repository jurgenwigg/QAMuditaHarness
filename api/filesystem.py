from harness.harness import Harness
from harness.request import Request, Response
from harness.interface.defs import Endpoint, Method
from harness import log
import base64
from tqdm import tqdm
import os
import binascii
from functools import partial
from .generic import GenericResponse, GenericTransaction


class FsInitResponse(GenericResponse):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rxID = self.response.body["rxID"]
        self.chunkSize = self.response.body["chunkSize"]
        self.fileSize = self.response.body["fileSize"]


class FsInitGet(GenericTransaction):
    '''
    Initialize filesystem Get transaction: Pure -> PC
    '''
    def __init__(self, path: str, filename: str):
        self.request = Request(Endpoint.FILESYSTEM, Method.GET, {"fileName": path + "/" + filename})

    def setResponse(self, response: Response):
        self.response = FsInitResponse(response)


class FsGetChunkResponse(GenericResponse):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bin_data = base64.standard_b64decode(self.response.body["data"][0:-1])


class FsGetChunk(GenericTransaction):
    '''
    Process single call to put next chunk of data Pure -> PC
    '''
    def __init__(self, id: int, chunkNo: int):
        self.request = Request(Endpoint.FILESYSTEM, Method.GET, {"rxID": id, "chunkNo": chunkNo})

    def setResponse(self, response: Response):
        self.response = FsGetChunkResponse(response)


def get_transfer(harness: Harness, logDir: str, fileName: str, rxID, fileSize, chunkSize):
    '''
    Incomplete function to get file - transfering data chunks only
    '''
    totalChunks = int(((fileSize + chunkSize - 1) / chunkSize))
    log.info(f'Transfering {fileName} to {logDir}:')
    with open(os.path.join(logDir, fileName), 'wb') as logFile:
        with tqdm(total=fileSize, unit='B', unit_scale=True) as p_bar:
            for n in range(1, totalChunks + 1):
                p_bar.update(chunkSize)
                ret = FsGetChunk(rxID, n).run(harness)
                logFile.write(ret.bin_data)


def get_file(harness: Harness, file_pure: str, file_local, path_pure: str = "/sys/user", file_user=""):
    '''
    Complete function to get file:
        - Request to init get file: FsInitGet
        - as many as it takes chunk transmissions: FsGetChunk (via get_transfer)
    printing pretty progress bar as it goes on
    '''
    if file_user == "":
        file_user = file_pure
    file_local = os.path.abspath(file_local)
    ret = FsInitGet(path_pure, file_pure).run(harness)
    get_transfer(harness, file_local, file_user, ret.rxID, ret.fileSize, ret.chunkSize)
    log.info(f"file {file_pure} complete")


def get_log_file(harness: Harness, log_dir: str):
    '''
    Function to download MuditaOS logs from system
    '''
    filename = "MuditaOS.log"
    get_file(harness, filename, log_dir)


class FsInitPutResponse(GenericResponse):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.txID = self.response.body["txID"]
        self.chunkSize = self.response.body["chunkSize"]


class FsInitPut(GenericTransaction):
    '''
    Initialize filesystem Put transaction: PC -> Phone
    '''
    def __init__(self, path: str, filename: str, size: int, crc32: str):
        self.request = Request(Endpoint.FILESYSTEM, Method.PUT, {"fileName": path + "/" + filename,
                                                                 "fileSize": size,
                                                                 "fileCrc32": crc32})

    def setResponse(self, response: Response):
        self.response = FsInitPutResponse(response)


class FsPutChunkResponse(GenericResponse):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class FsPutChunk(GenericTransaction):
    '''
    Transaction putting single file chunk on Pure, depends on FsInitPut
    '''
    def __init__(self, txID: int, chunkNo: int, data: bytearray):
        self.request = Request(Endpoint.FILESYSTEM, Method.PUT, {"txID": txID,
                                                                 "chunkNo": chunkNo,
                                                                 "data": data})

    def setResponse(self, response: Response):
        self.response = FsPutChunkResponse(response)


def put_file(harness: Harness, file: str, where: str):
    '''
    Complete function to put file to Pure:
        - Request to init get file: FsInitPut
        - as many as it takes chunk transmissions: FsPutChunk (via get_transfer)
    printing pretty progress bar as it goes on
    '''
    fileSize = os.path.getsize(file)
    with open(file, 'rb') as l_file:
        file_data = l_file.read()
        fileCrc32 = format((binascii.crc32(file_data) & 0xFFFFFFFF), '08x')

    ret = FsInitPut(where, file, fileSize, fileCrc32).run(harness)
    chunkNo = 1

    with open(file, 'rb') as l_file:
        with tqdm(total=fileSize, unit='B', unit_scale=True) as p_bar:
            for chunk in iter(partial(l_file.read, ret.chunkSize), b''):
                FsPutChunk(ret.txID, chunkNo, base64.standard_b64encode(
                    chunk).decode()).run(harness)
                chunkNo += 1
                p_bar.update(ret.chunkSize)