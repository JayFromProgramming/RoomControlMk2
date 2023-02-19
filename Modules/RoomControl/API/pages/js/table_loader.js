
device_name_cache = {};

function button(actionLink, displayName) {
    return '<a href="' + actionLink + '" class="button">' + displayName + '</a>';
}

function getName(id) {
    var name = "";
    if (id in device_name_cache) {
        return device_name_cache[id];
    } else {
        $.ajax({
            url: "/name/" + id,
            type: "GET",
            async: false,
            success: function (data) {
                name = data;
                device_name_cache[id] = name;
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
            state_string += (toggleDeviceState(device_json) + ",").padEnd(12, " ");
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
                state_string += "State: Armed" + ", ";
                if (device_json["state"]["triggered"] === 1) {
                    state_string += "Triggered:" + " " + device_json["state"]["active_for"].toFixed(2) + "S";
                } else {
                    const last_active = new Date(device_json["state"]["last_active"]);
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

function getAction(id) {
    var action = "";
    $.ajax({
        url: "/get_action_string/" + id,
        type: "GET",
        async: false,
        success: function (data) {
            action = data;
        }
    });
    return action;
}

// A class to handle sending a command to the server without refreshing the page
class ActionButton {
    constructor(name, action, enabled) {
        this.name = name;
        this.action = action; // String of the api action
        this.button = document.createElement("button");
        this.button.innerHTML = this.name;
        this.button.onclick = this.onClick;
        this.button.name = this.action;
        this.button.enabled = enabled;
    }

    onClick() {
        $.ajax({
            url: "/set/" + this.name,
            type: "get",
            success: function (result) {

            },
            error: function (result) {

            }
        })
    }

    getButton() {
        return this.button;
    }

}


function device_table() {
    $.ajax({
        url: "/get_all",
        type: "GET",
        dataType: "json",
        success: function (data) {
            let toggle_button;
            const devices = data.devices; // A dictionary of devices and their data
            const device_table = $('#device_list_body');

            device_table.empty();
            for (const device in devices) {
                const device_data = devices[device];
                const device_row = $('<tr>');
                const name = getName(device);
                const device_name = $('<td class="device_name">').text(name);

                const is_on = device_data["state"]["on"];
                const is_down = !device_data["health"]["online"];
                if (device === "plug_1") {
                    if (is_on) {
                        toggle_button = new ActionButton("Locked", device + "?on=true", false);
                    } else {
                        toggle_button = new ActionButton("Turn On", device + "?on=true", !is_down);
                    }
                } else {
                    if (is_on) {
                        toggle_button = new ActionButton("Turn Off", device + "?on=false", !is_down);
                    } else {
                        toggle_button = new ActionButton("Turn On", device + "?on=true", !is_down);
                    }
                }

                const device_toggle = $('<td>').html(toggle_button.getButton());
                const device_status = $('<td class="device_details">').text(getState(device_data));
                const device_health = $('<td class="device_health">').html(getHealth(device_data));

                device_row.append(device_name);
                device_row.append(device_toggle);
                device_row.append(device_status);
                device_row.append(device_health);
                device_table.append(device_row);
            }
            // Add a footer spans the entire table that shows the last time the page was updated,
            // set the color to black
            var footer = $('<tr>');
            var footer_text = $('<td>').text("Last Updated: " + new Date().toLocaleString());
            footer_text.attr("colspan", 4);
            footer_text.css("color", "black");
            footer.append(footer_text);
            device_table.append(footer);
        },
        error: function (xhr, status, error) {
            // Set the footer text to red, but don't change the text
            var footer = $('#device_list_body tr:last-child');
            footer.css("color", "red");

        }
    });
}

$(document).ready(device_table());

// Make the above code run every 5 seconds without refreshing the page

setInterval(device_table, 5000);