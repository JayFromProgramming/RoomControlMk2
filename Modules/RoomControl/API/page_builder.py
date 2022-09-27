import sys

from aiohttp import web


def light_color_stringify(data):
    return f"On: {data['on']}, Brightness: {str(data['brightness']).zfill(3)}" \
           f"\r\nColor: {data['color']}"


def state_to_string(device):
    match device.get_type():
        case 'abstract_rgb':
            return light_color_stringify(device.get_state())
        case 'abstract_toggle_device':
            return f"On: {device.is_on()}, Auto: {device.auto_state()['is_auto']}"
        case 'VoiceMonkeyDevice':
            return f"On: {device.is_on()}, Auto: {device.auto_state()['is_auto']}"
        case 'environment_controller':
            return f"Current Value: {device.current_value}{device.unit}, Setpoint: {device.setpoint}{device.unit}, " \
                   f"{'Enabled' if device.on else 'Disabled'}"


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
    if "fault" in device.get_health() and device.get_health()["fault"] is True:
        return f"FAULT: {device.get_health()['reason']}"
    elif device.get_health()["online"]:
        return "ONLINE"
    else:
        return f"OFFLINE: {device.get_health()['reason']}"


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
                <td><a href="/set/{device.name()}?on={str(not device.on).lower()}?redirect=true">
                {'Turn on' if not device.on else 'Turn off'}</a></td>
                <td>{state_to_string(device)}</td>
                <td>{health_message(device)}</td>
            </tr>
            """

        page = file.read().replace("{device_table}", table)

        return web.Response(text=page, content_type="text/html", headers={"Refresh": "5"})


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
