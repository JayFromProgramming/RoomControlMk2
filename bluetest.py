from bluepy.btle import Scanner, DefaultDelegate, Peripheral
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
    return "Unknown"


def getPeripheral(device):
    try:
        if device.addrType == "random":
            print("Random address, skipping")
            return None
        p = Peripheral(device.addr, device.addrType)
        return p
    except Exception as e:
        print(f"Failed to connect to {device.addr} with error: {e}")
        return None


scanner = Scanner().withDelegate(ScanDelegate())
devices = scanner.scan(10.0)

for dev in devices:
    print(f"Device {dev.addr} ({dev.addrType}), RSSI={dev.rssi} dB")
    for (adtype, desc, value) in dev.getScanData():
        if adtype == 255:
            print(f"{str(adtype).ljust(3)}:  {desc} = {value}")
            print(f"    Company Name: {findCompany(value)}")
        else:
            print(f"{str(adtype).ljust(3)}:  {desc} = {value}")

    p = getPeripheral(dev)
    if p:
        print("Services:")
        services = p.getServices()
        for service in services:
            print(f"Service: {service.uuid}")
            for characteristic in service.getCharacteristics():
                print(f"    Characteristic: {characteristic.uuid}")
                print(f"        Properties: {characteristic.propertiesToString()}")
                print(f"        Value: {characteristic.read()}")
                print(f"        Descriptors: {characteristic.getDescriptors()}")
                for descriptor in characteristic.getDescriptors():
                    print(f"            Descriptor: {descriptor.uuid}")
                    print(f"                Value: {descriptor.read()}")
        p.disconnect()
    else:
        print("No services available")
    print("----------------------------------------")
