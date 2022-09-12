import sys

from aiohttp import web


def light_color_stringify(data):
    return f"On: {data['on']}, Brightness: {data['brightness']}" \
           f"\r\nColor: {data['color']}"


def state_to_string(device):
    match device.get_type():
        case 'abstract_rgb':
            return light_color_stringify(device.get_state())
        case 'abstract_toggle_device':
            return f"On: {device.is_on()}"
        case 'VoiceMonkeyDevice':
            return f"On: {device.is_on()}"


def generate_device_buttons(device):
    """Generate raw html buttons to send commands to the device, don't have clicking the button leave the page"""
    # This generates the buttons within the control form
    controls = f"""
        <button class="button button1">{'Turn on' if not device.is_on() else 'Turn off'}</button>
    """

    match device.get_type():
        case 'abstract_rgb':
            controls += f"""
                <input type="slider" name="brightness" value="{device.get_state()['brightness']}" min="0" max="255">
                <input type="color" name="color" value="{device.get_state()['color']}">
                <
            """
        case 'abstract_toggle_device':
            pass
        case 'VoiceMonkeyDevice':
            pass

    return controls


def generate_main_page(self):
    with open(f"{sys.path[0]}/Modules/RoomControl/API/pages/main_view_page.html", "r") as file:
        # Replace {device_table} with the table of devices
        # Each device row should have a button to turn it on/off

        # Any buttons are links not javascript

        # The table should also be centered on the page

        table = ""

        # Add table header
        table += "<tr><th>Device Name</th><th>Control Device</th><th>Device Status</th><th>Device Health</th></tr>"
        # Add borders to the table
        table += "<style>table, th, td {border: 1px solid black;}</style>"

        for device in self.get_all_devices():
            # For offline devices, have the text be red
            if not device.online:
                table += f"<tr style='color:red'>"
            else:
                table += "<tr>"

            table += f"""
                <td>{self.get_device_display_name(device.name())}</td>
                <td><form action="/web_control/{device.name()}" method="get">
                    <input type="submit" value="Open Device" {'DISABLED' if not device.get_health()["online"] else ''}>
                </form></td>
                <td>{state_to_string(device)}</td>
                <td>{'ONLINE' if device.get_health()["online"] else f'OFFLINE: {device.get_health()["reason"]}'}</td>
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
