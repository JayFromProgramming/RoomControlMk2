function button (actionLink, displayName){
    return '<a href="' + actionLink + '" class="button">' + displayName + '</a>';
}

function getName(id){
    var name = "";
    $.ajax({
        url: "name/" + id,
        type: "GET",
        async: false,
        success: function(data){
            name = data;
        }
    });
    return name;
}

function getState(id){
    var state = "";
    $.ajax({
        url: "get_status_string/" + id,
        type: "GET",
        async: false,
        success: function(data){
            state = data;
        }
    });
    return state;
}

function getHealth(id){
    var health = "";
    $.ajax({
        url: "get_health_string/" + id,
        type: "GET",
        async: false,
        success: function(data){
            health = data;
        }
    });
    return health;
}

function getAction(id){
    var action = "";
    $.ajax({
        url: "get_action_string/" + id,
        type: "GET",
        async: false,
        success: function(data){
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
          success: function(result) {

          },
          error: function(result) {

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
            var devices = data.devices; // A dictionary of devices and their data
            var device_table = $('#device_list_body');

            device_table.empty();
               for (var device in devices) {
                    var device_data = devices[device];
                    var device_row = $('<tr>');
                    var name = getName(device);
                    var device_name = $('<td>').text(name);

                    var is_on = device_data["state"]["on"];
                    var is_down = !device_data["health"]["online"];
                    if (is_on) {
                        var toggle_button = new ActionButton("Turn Off", device + "?on=false", !is_down);
                    } else {
                        var toggle_button = new ActionButton("Turn On", device + "?on=true", !is_down);
                    }

                    var device_toggle = $('<td>').html(toggle_button.getButton());
                    var device_status = $('<td>').text(getState(device));
                    var device_health = $('<td>').html(getHealth(device));

                    device_row.append(device_name);
                    device_row.append(device_toggle);
                    device_row.append(device_status);
                    device_row.append(device_health);
                    device_table.append(device_row);
                }
                // Add a footer spans the entire table that shows the last time the page was updated
                var footer = $('<tr>');
                var footer_text = $('<td>').text("Last Updated: " + new Date().toLocaleString());
                footer_text.attr("colspan", 4);
                footer.append(footer_text);
                device_table.append(footer);
        },
        error: function (xhr, status, error) {
            console.log("Error: " + error.message);
            // Don't do anything if there's an error
        }
    });
}

$(document).ready(device_table());

// Make the above code run every 5 seconds without refreshing the page

setInterval(device_table, 5000);