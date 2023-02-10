from bluepy.btle import Scanner, DefaultDelegate
from companyInfo import companyData


class ScanDelegate(DefaultDelegate):
    def __init__(self):
        DefaultDelegate.__init__(self)

    def handleDiscovery(self, dev, isNewDev, isNewData):
        if isNewDev:
            print(f"Discovered device {dev.addr}, {dev.addrType}, {dev.rssi}")
        elif isNewData:
            print(f"Received new data from {dev.addr}")


def findCompany(companyId):
    for company in companyData:
        if company["Decimal"] == companyId:
            return company["Company"]


scanner = Scanner().withDelegate(ScanDelegate())
devices = scanner.scan(10.0)

for dev in devices:
    print(f"Device {dev.addr} ({dev.addrType}), RSSI={dev.rssi} dB")
    for (adtype, desc, value) in dev.getScanData():
        if adtype == 9:
            print(f"{str(adtype).ljust(3)}:  {desc} = {value}")
            if value in companyData:
                print(f"    Company Name: {findCompany(value)}")
        else:
            print(f"{str(adtype).ljust(3)}:  {desc} = {value}")
