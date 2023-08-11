let device_name_cache = {};
let raw_device_name_cache = localStorage.getItem("device_name_cache");
if (raw_device_name_cache === null) {
    raw_device_name_cache = "{}";
}
device_name_cache = JSON.parse(raw_device_name_cache);
let device = null;
let device_list = null;

function getName(id) {
    // Use localStorage to cache device names
    let name = id;
    if (device_name_cache[id] !== undefined) {
        name = device_name_cache[id];
    } else { // Queue the name to be fetched, but don't wait for it
        $.ajax({
            url: "/name/" + id,
            type: "GET",
            async: true,  // Don't wait for the response
            success: function (data) {
                name = data;
                device_name_cache[id] = name;
                localStorage.setItem("device_name_cache", JSON.stringify(device_name_cache));
            }
        });
    }
    return name;
}

function getDeviceData(device_id) {
    // Get the device data from the server
    let device_data = null;
    $.ajax({
        url: '/get/' + device_id,
        type: 'GET',
        dataType: 'json',
        async: false,
        success: function(data) {
            device_data = data;
        },
        error: function(data) {
            console.log("Error getting device data");
        }
    });
    return device_data;
}


class Device {
    constructor(name, id, json_info) {
        console.log("Creating device " + name + " with id " + id + " and info " + json_info);
        this.id = id;
        this.name = name;
        this.state = json_info.state;
        this.type = json_info.type;
        this.info = json_info.info;
        this.ui_elements = [];
        // Based on the devices type attach the appropriate UI elements and the default UI elements
        // Eg. If the device is a light, attach a color selector and a brightness slider in addition to the toggle switch
        // If the device is a thermostat, attach a temperature slider and a mode selector in addition to the toggle switch
        this.ui_elements.push(new ToggleSwitch(id));
        switch (this.type) {
            case "abstract_rgb":
                this.ui_elements.push(new ColorSelector("#000000", id));
                break;
            case "environment_controller":
                this.ui_elements.push(new SetpointSelector(this.state.target_value, id, this.info.units));
                break;
            case "light_controller":
                this.ui_elements.push(
                    new ToggleSwitch(id,"dnd_active", "Set DND", "enable_dnd"));
                break;
            default:
                break;
        }
    }

    getElements() {
        // Return the UI elements
        return this.ui_elements;
    }

    updateData(json_data) {
        // Update the UI elements with the new data
        for (let i = 0; i < this.ui_elements.length; i++) {
            this.ui_elements[i].updateData(json_data);
        }
    }

}

function periodic_update() {
    // Periodically update the device data
    if (device !== null) {
        device.updateData(getDeviceData(device.id));
        device_list.device_updated();
        // Check if the device container is empty
        if ($("#device_container").children().length === 0) {
            // If it is, add the device elements back
            const device_elements = device.getElements();
            for (let i = 0; i < device_elements.length; i++) {
                $("#device_container").append(device_elements[i].getContainer());
            }
        }
    }
}

function initialize_page(){
    // Check if the page was loaded with a device argument

    const params = new URLSearchParams(window.location.search);
    const default_device = params.get('device');
    if (default_device !== null) {
        starting_device = default_device;
    } else {
        starting_device = null;
    }
    device_list = new DeviceList(starting_device, function(device_id, list_obj) {
        // Callback function to be called when the selected device changes
        // Create a new DeviceObject and add it to the page
        $("#device_container").empty();
        const device_name = getName(device_id);
        device = new Device(device_name, device_id, getDeviceData(device_id));
        const device_elements = device.getElements();
        for (let i = 0; i < device_elements.length; i++) {
            console.log("Adding element " + device_elements[i]);
            $("#device_container").append(device_elements[i].getContainer());
        }
    });


    // Add the device list to the page
    var center_div = $("#center-column");

    center_div.append(device_list.getContainer());

    setInterval(periodic_update, 1500);
}



$(document).ready(initialize_page());