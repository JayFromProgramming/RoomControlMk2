import sys

from aiohttp import web


def light_color_stringify(data):
    return f"On: {data['on']}, Brightness: {str(data['brightness']).zfill(3)}" \
           f"\r\nColor: {data['color']}"


def toggle_device_state_description(device):
    if "fault" in device.get_health() and device.get_health()["fault"] is True:
        return "FAULT"
    elif device.get_health()["online"] is False:
        return "DOWN"
    if device.is_on() and device.auto_state()["is_auto"]:
        return "AUTO"
    elif device.is_on() and not device.auto_state()["is_auto"]:
        return "ON"
    elif not device.is_on() and device.auto_state()["is_auto"]:
        return "IDLE"
    elif not device.is_on() and not device.auto_state()["is_auto"]:
        return "OFF"


def pin_state_description(device):
    state = device.get_state()
    active_time = state["active_for"]
    if device.get_health()["fault"]:
        return f"FAULT"
    if state["on"]:
        if state["triggered"]:
            return f"Active: {active_time}s"
        else:
            return "Armed"
    else:
        return "Disabled"


def blue_stalker_state(device):
    state = device.get_state()
    info = device.get_info()
    health = device.get_health()
    if not state["on"]:
        return "State: Disabled"
    if health["fault"]:
        return "State: Fault"
    if not health["online"]:
        return "State: DOWN"
    if state['occupied']:
        return f"Occupants: {', '.join(state['occupants'])}"
    else:
        return f"Not Occupied, AutoScan: {state['auto_scan']}"

def auto_light_controller_state_string(device):
    state = device.get_state()
    if state["on"]:
        match state["current_state"]:
            case 0:
                return "State: IDLE"
            case 1:
                return "State: ACTIVE"
            case 2:
                return "State: TRIGGERED"
            case 3:
                return "State: FAULT"
            case _:
                return "State: UNKNOWN"
    else:
        return "State: DISABLED"


def state_to_string(device):
    match device.get_type():
        case 'abstract_rgb':
            return light_color_stringify(device.get_state())
        case 'abstract_toggle_device':
            return f"State: {toggle_device_state_description(device)}"
        case 'VoiceMonkeyDevice':
            return f"State: {toggle_device_state_description(device)}"
        case 'environment_controller':
            return f"Current Value: {device.current_value}{device.unit}, Setpoint: {device.setpoint}{device.unit}, " \
                   f"{'Enabled' if device.on else 'Disabled'}"
        case 'pin_watcher':
            return f"State: {pin_state_description(device)}"
        case 'blue_stalker':
            return blue_stalker_state(device)
        case 'light_controller':
            return auto_light_controller_state_string(device)
        case _:
            return "Device type not implemented"


def generate_device_buttons(device):
    """Generate raw html buttons to send commands to the device, don't have clicking the button leave the page"""
    # This generates the buttons within the control form
    controls = f"""
        <button class="button button1">{'Turn on' if not device.is_on() else 'Turn off'}</button>
    """

    match device.get_type():
        case 'abstract_rgb':
            controls += f"""
                <input type="slider" name="brightness" value="{device.get_state()['brightness'].zpad(3)}" min="0" max="255">
                <input type="color" name="color" value="{device.get_state()['color']}">
                <
            """
        case 'abstract_toggle_device':
            pass
        case 'VoiceMonkeyDevice':
            pass

    return controls


def health_message(device):
    if "online" in device.get_health() and device.get_health()["online"] is False:
        return f"<span style='color:red'>OFFLINE: {device.get_health()['reason']}</span>"
    if "fault" in device.get_health() and device.get_health()["fault"] is True:
        return f"<span style='color:red'>FAULT: {device.get_health()['reason']}</span>"
    elif device.get_health()["online"]:
        return "<span style='color:green'>ONLINE</span>"
    else:
        return "<span style='color:red'>UNKNOWN</span>"


def generate_actions(device):
    return f"""<td> <a href="/set/{device.name()}?on={str(not device.on).lower()}">
    {'Turn on' if not device.on else 'Turn off'} </a></td>"""


def generate_main_page(self):
    with open(f"{sys.path[0]}/Modules/RoomControl/API/pages/main_view_page.html", "r") as file:
        # Replace {device_table} with the table of devices
        # Each device row should have a button to turn it on/off

        # Any buttons are links not javascript

        # The table should also be centered on the page

        table = ""

        # Add table header
        table += "<tr><th>Device Name</th><th>Toggle Device</th><th>Device Status</th><th>Device Health</th></tr>"
        # Add borders to the table
        table += "<style>table, th, td {border: 1px solid black;}</style>"

        for device in self.get_all_devices():
            # For offline devices, have the text be red
            if not device.online or ("fault" in device.get_health() and device.get_health()["fault"] is True):
                table += f"<tr style='color:red'>"
            else:
                table += "<tr>"

            table += f"""
                <td>{self.get_device_display_name(device.name())}</td>
                
                <td>{state_to_string(device)}</td>
                <td>{health_message(device)}</td>
            </tr>
            """

        page = file.read().replace("{device_table}", table)

        return web.Response(text=page, content_type="text/html")


def generate_control_page(self, device):
    with open(f"{sys.path[0]}/Modules/RoomControl/API/pages/control_page.html", "r") as file:
        # Replace {body} with the body of the page

        control_form = f"""
            <form action="/web_control/{device.name()}" method="post">
                {generate_device_buttons(device)}
            </form>
        """

        page = file.read().replace("{body}", control_form)

    return web.Response(text=page, content_type="text/html", headers={"Refresh": "5"})
