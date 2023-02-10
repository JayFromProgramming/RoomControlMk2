from bluepy.btle import Scanner, DefaultDelegate, Peripheral, BTLEDisconnectError
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
        try:
            print("Services:")
            services = p.getServices()
            for service in services:
                print(f"    Service: {service.uuid}")
                print("        Characteristics:")
                characteristics = service.getCharacteristics()
                for characteristic in characteristics:
                    print(f"            Characteristic: {characteristic.uuid}")
                    if characteristic.supportsRead():
                        print(f"                Value: {characteristic.read()}")
                    else:
                        print(f"                Value: (Not readable)")
                    print(f"                Properties: {characteristic.propertiesToString()}")
                    print(f"                Descriptors:")
                    descriptors = characteristic.getDescriptors()
                    for descriptor in descriptors:
                        print(f"                    Descriptor: {descriptor.uuid}")
                        try:
                            print(f"                        Value: {descriptor.read()}")
                        except Exception as e:
                            print(f"                        Value: (Not readable)")
            p.disconnect()
        except BTLEDisconnectError as e:
            print(f"-------ERROR DEVICE DISCONNECTED-------")
    else:
        print("No services available")
    print("----------------------------------------")
