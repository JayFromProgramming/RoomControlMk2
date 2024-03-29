var device_name_cache = {};
var raw_device_name_cache = localStorage.getItem("device_name_cache");
if (raw_device_name_cache === null) {
    raw_device_name_cache = "{}";
}
var device_name_cache = JSON.parse(raw_device_name_cache);

var raw_device_data_cache = sessionStorage.getItem("device_data_cache");
if (raw_device_data_cache === null) {
    raw_device_data_cache = "{}";
}
var device_data_cache = JSON.parse(raw_device_data_cache);

var first_load = true;
var device_table_objects = {};
var footer;

// function button(actionLink, displayName) {
//     return '<a href="' + actionLink + '" class="button">' + displayName + '</a>';
// }

function getName(id) {
    // Use localStorage to cache device names
    var name = id;
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

function toggleDeviceState(device_json) {
    if (device_json["health"]["fault"] === true) {
        return "State: FAULT";
    } else if (device_json["health"]["online"] === false) {
        return "State: DOWN";
    } else if (device_json["state"]["on"] === true && device_json["auto_state"]["is_auto"] === false) {
        return "State: ON";
    } else if (device_json["state"]["on"] === false && device_json["auto_state"]["is_auto"] === false) {
        return "State: OFF";
    } else if (device_json["state"]["on"] === true && device_json["auto_state"]["is_auto"] === true) {
        return "State: AUTO";
    } else if (device_json["state"]["on"] === false && device_json["auto_state"]["is_auto"] === true) {
        return "State: IDLE";
    } else {
        return "State: UNKNOWN";
    }
}

function getState(device_json) {
    var state_string = "";

    switch (device_json["type"]) {
        case "abstract_rgb":
            if (device_json["state"]["on"] === true) {
                state_string += "ON,  ";
            } else {
                state_string += "OFF, ";
            }
            if (device_json["state"]["white_enabled"] === true) {
                state_string += "Brightness: " +
                    (device_json["state"]["brightness"] / 255 * 100).toFixed(0) + "%";
            } else {
                state_string += "Color: " + device_json["state"]["color"];
            }
            break;
        case "abstract_toggle_device":
            state_string += (toggleDeviceState(device_json) + ",").padEnd(13, " ");
            state_string += "Power Draw: " + device_json["info"]["power"] + "W";
            break;
        case "VoiceMonkeyDevice":
            state_string += toggleDeviceState(device_json);
            break;
        case "environment_controller":
            state_string += "Current Value: " + device_json["state"]["current_value"].toFixed(2)
                + device_json["info"]["units"];
            state_string += ", Target Value: " + device_json["state"]["target_value"].toFixed(2)
                + device_json["info"]["units"];
            if (device_json["state"]["on"] === true) {
                state_string += ", Enabled";
            } else {
                state_string += ", Disabled";
            }
            break;
        case "light_controller":
            if (device_json["state"]["on"] === true) {
                switch (device_json["state"]["current_state"]) {
                    case 0:
                        state_string += "State: IDLE";
                        break;
                    case 1:
                        state_string += "State: ACTIVE"
                        break;
                    case 2:
                        state_string += "State: TRIGGERED"
                        break;
                    case 3:
                        state_string += "State: FAULT"
                        break;
                    case 4:
                        state_string += "State: DND";
                        break;
                    default:
                        state_string += "State: UNKNOWN"
                }
            } else {
                state_string += "State: DISABLED";
            }
            break;
        case "blue_stalker":
            if (device_json["state"]["on"] === true) {
                if (device_json["health"]["fault"] === true) {
                    state_string += "State: FAULT";
                } else if (device_json["health"]["online"] === false) {
                    state_string += "State: DOWN";
                } else if (device_json["state"]["occupied"] === true) {
                    state_string += "Occupants: " + device_json["state"]["occupants"]
                } else {
                    state_string += "No Occupants";
                }
            } else {
                state_string += "State: DISABLED";
            }
            break;
        case "pin_watcher":
            if (device_json["health"]["online"] === false) {
                state_string += "State: DOWN";
            } else if (device_json["health"]["fault"] === true) {
                state_string += "State: FAULT";
            } else if (device_json["state"]["on"] === true) {
                if (device_json["state"]["triggered"] === 1) {
                    state_string += "State: Triggered" + " " + device_json["state"]["active_for"].toFixed(2) + "S";
                } else {
                    state_string += "State: Armed" + ", ";
                    const last_active = new Date(device_json["state"]["last_active"] * 1000);
                    state_string += "Last Active: " + last_active.toLocaleString();
                }
            } else {
                state_string += "State: Disarmed";
            }
    }

    return state_string;
}

function getHealth(device_json) {
    var health_string;
    var health_json = device_json["health"];
    if (health_json["online"] === false) {
        health_string = "<span style='color:red'>OFFLINE: " + health_json["reason"] + "</span>";
    } else if (health_json["fault"] === true) {
        health_string = "<span style='color:red'>FAULT: " + health_json["reason"] + "</span>";
    } else if (health_json["online"] === true) {
        health_string = "<span style='color:green'>ONLINE</span>";
    } else {
        health_string = "<span style='color:orange'>UNKNOWN</span>";
    }
    return health_string;
}

function getAction(id, is_on) {
    // Endpoint "/set/{name}?on=!{state}" to toggle the state of a device
    var action_string = "";
    if (is_on === true) {
        action_string += "/set/" + id + "?on=false";
    } else {
        action_string += "/set/" + id + "?on=true";
    }
    return action_string;
}

function getButtonText(state){
    if (state["on"] === true) {
        return "Turn Off";
    } else {
        return "Turn On";
    }
}

class DeviceObject {
    constructor(device, device_json) {
        this.id = device;
        this.name = getName(device);
        this.row = document.createElement("tr");
        this.button = document.createElement("td");
        this.row.id = this.id;
        this.row.className = "device_row";
        this.on = device_json["state"]["on"];
        this.request_success = true;



        this.button = document.createElement("button");
        this.button.className = "btn btn-primary";
        this.button.innerHTML = getButtonText(device_json["state"]);
        this.button.onclick = this.onClick.bind(this);
        // Add each element in this order Name, Button, State, Health
        this.name_row = document.createElement("td");
        this.name_row.classList.add('device_name');
        this.button_row = document.createElement("td");
        this.state_row = document.createElement("td");
        this.state_row.classList.add('device_details');
        this.health_row = document.createElement("td");
        this.health_row.classList.add('device_health');

        // The device name should be a link to the device page (/page/control_page?device={device_id})
        this.name_row.innerHTML = "<a href='/page/control_page?device=" + this.id + "'>" + this.name + "</a>";
        this.state_row.innerHTML = getState(device_json);
        this.health_row.innerHTML = getHealth(device_json);
        this.button_row.appendChild(this.button);

        this.row.appendChild(this.name_row);
        this.row.appendChild(this.button_row);
        this.row.appendChild(this.state_row);
        this.row.appendChild(this.health_row);

        this.locked = false;
        // if (this.id === "plug_1") {
        //     this.locked = true;
        //     this.button.disabled = true;
        //     this.button.innerHTML = "Locked";
        // }

        this.updateRow(device_json);
    }

    onClick() {
        this.button.disabled = true;
        this.request_success = false;
        $.ajax({
            url: getAction(this.id, this.on),
            owner: this,
            type: "get",
            success: function (result) {
                this.owner.request_success = true;
            },
            error: function (result) {
            }
        })
    }

    getRow() {
        return this.row;
    }

    updateRow(new_json) {
        if (this.button.disabled === true && this.request_success === true && this.locked === false) {
            this.button.disabled = false;
        }
        this.on = new_json["state"]["on"];
        this.button.innerHTML = getButtonText(new_json["state"]);
        this.state_row.innerHTML = getState(new_json);
        this.health_row.innerHTML = getHealth(new_json);
    }
}


function update_table(data) {
    let toggle_button;
    const devices = data.devices; // A dictionary of devices and their data
    var device_table = $("#device_list_body");


    // For each device check if its object exists if not create it
    for (let device in devices) {
        let device_object = device_table.find("#" + device);
        if (device_object.length === 0) {
            // Create a new device object
            let device_object = new DeviceObject(device, devices[device]);
            // Add the device to the table
            device_table.append(device_object.getRow());
            device_table_objects[device] = device_object;
        } else {
            // Update the device object
            device_object = device_table_objects[device];
            device_object.updateRow(devices[device]);
            // Update the device in the table
//             device_table.find("#" + device).updateRow(devices[device].get_row());
        }
    }

    // Update the footer
    var footer_text = device_table.find("#footer_text");
    if (footer_text.length === 0) {
//         console.log("Adding footer");
        var footer = document.createElement("tr");
        var footer_text = document.createElement("td");
        footer_text.colSpan = 4;
        device_table.append(footer);
        footer.appendChild(footer_text);
        footer_text.innerHTML = "Last Updated: " + new Date().toLocaleString();
        footer_text.id = "footer_text";
    } else {
        footer_text.html("Last Updated: " + new Date().toLocaleString());
    }
    // Update the footer text
}


function gen_device_table() {
// Display a cached version of the device table before the ajax call
    if (first_load === true && device_data_cache.devices !== undefined) {
        device_table = $("#device_list_body");
        console.log("Using cached data");
        update_table(device_data_cache);
        first_load = false;
//         return;
    }
    device_table = $("#device_list_body");
    $.ajax({
        url: "/get_all",
        type: "GET",
        dataType: "json",
        async: true,
        cache: false,
        error: function (xhr, status, error) {
            // Set the footer text to red, but don't change the text
            var footer = device_table.find("tr:last");
            footer.find("td").css("color", "red");
            // Find all the buttons and disable them
            var buttons = device_table.find("button");
            buttons.each(function () {
                this.disabled = true;
            });
        },
        success: function (data) {
            update_table(data);
            sessionStorage.setItem("device_data_cache", JSON.stringify(data));
        },
    });
}

function initialize_page() {
    // Get the pre-existing device table
    // Iterate through all elements in the table and remove them
    device_table = $("#device_list_body");
    device_table.find("tr").remove();


    gen_device_table();
    setInterval(gen_device_table, 5000);

}



$(document).ready(initialize_page());
