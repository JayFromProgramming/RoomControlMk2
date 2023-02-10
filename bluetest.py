from bluepy.btle import Scanner, DefaultDelegate, Peripheral, BTLEDisconnectError
from companyInfo import companyData


class ScanDelegate(DefaultDelegate):
    def __init__(self):
        DefaultDelegate.__init__(self)

    def handleDiscovery(self, dev, isNewDev, isNewData):
        if dev.addrType == "random":
            return
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
        # try:
        #     p.connect(device.addr)
        # except BTLEDisconnectError as e:
        #     print(f"Failed to connect to {device.addr} with error: {e}")
        return p
    except Exception as e:
        print(f"Failed to connect to {device.addr} with error: {e}")
        return None


scanner = Scanner().withDelegate(ScanDelegate())
devices = scanner.scan(10.0)

for dev in devices:
    if dev.addrType == "random":
        continue
    p = getPeripheral(dev)
    print(f"Device {dev.addr} ({dev.addrType}), RSSI={dev.rssi} dB")
    for (adtype, desc, value) in dev.getScanData():
        if adtype == 255:
            print(f"{str(adtype).ljust(3)}:  {desc} = {value}")
            print(f"    Company Name: {findCompany(value)}")
        else:
            print(f"{str(adtype).ljust(3)}:  {desc} = {value}")

    if p:
        try:
            services = p.getServices()
            print(f"Services ({len(services)}):")
            for service in services:
                try:
                    print(f"    Service: {service.uuid}")
                    characteristics = service.getCharacteristics()
                    print(f"        Characteristics ({len(characteristics)}):")
                    for characteristic in characteristics:
                        try:
                            print(f"            Characteristic: {characteristic.uuid}")
                            if characteristic.supportsRead():
                                print(f"                Value: {characteristic.read()}")
                                print(f"                Properties: {characteristic.propertiesToString()}")
                            else:
                                print(f"                Value: (Not readable)")
                            descriptors = characteristic.getDescriptors()
                            if len(descriptors) > 0:
                                print("                Descriptors:")
                                for descriptor in descriptors:
                                    print(f"                    Descriptor: {descriptor.uuid}")
                                    try:
                                        print(f"                        Value: {descriptor.read()}")
                                    except Exception as e:
                                        print(f"                        Value: (Not readable)")
                            else:
                                print("                No descriptors available")
                        except Exception as e:
                            print(f"            └──> Failed with error: {e}")
                except Exception as e:
                    print(f"        └──> Failed with error: {e}")
            p.disconnect()
        except BTLEDisconnectError as e:
            print(f"-------ERROR DEVICE DISCONNECTED UNEXPECTEDLY-------")
        except Exception as e:
            print(f"-------ERROR DEVICE FAILED WITH ERROR: {e}-------")
    else:
        print("No services available")
    print("----------------------------------------")
