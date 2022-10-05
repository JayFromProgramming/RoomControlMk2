function button (actionLink, displayName){
    return '<a href="' + actionLink + '" class="button">' + displayName + '</a>';
}

function getName(id){
    var name = "";
    $.ajax({
        url: "/name/" + id,
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
        url: "/get_status_string/" + id,
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
        url: "/get_health_string/" + id,
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
        url: "/get_action_string/" + id,
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

function scene_table() {
    $.ajax({
        url: "/get_scenes",
        type: "GET",
        dataType: "json",
        success: function (data) {
            let toggle_button;
            const scenes = data.scenes; // A dictionary of devices and their data
            const scene_table = $('#scene_list_body');

            scene_table.empty();
               for (const scene in scenes) {
                   const scene_data = scenes[scene];
                   const scene_row = $('<tr>');
                   const name = scene_data['name'];
                   const scene_name = $('<td class="device_name">').text(name);

                   const is_active = scene_data['active'];
                   const trigger_type = scene_data['trigger_type']
                   const trigger_value = scene_data['trigger_value']

                   if (trigger_type === "immediate") {
                        toggle_button = new ActionButton("Execute", scene, true);
                    } else {
                        if (is_active) {
                            toggle_button = new ActionButton("Deactivate", scene, true);
                        } else {
                            toggle_button = new ActionButton("Activate", scene, true);
                        }
                    }

                   let scene_action_raw = scene_data['action'];
                   // Format the names out of the action string, e.g "Turns [B4E842D7A9F8] on" -> "Turns Living Room on"
                     let scene_action_text = scene_action_raw.replace(/\[([^\]]+)\]/g,
                         function(match, contents, offset, input_string) {
                                return getName(contents);
                         }
                        );

                   const scene_command = $('<td>').html(toggle_button.getButton());
                   const scene_action = $('<td>').text(scene_action_text);
                   let trigger_text = "";
                   if (trigger_type === "immediate") {
                       trigger_text = $('<td>').text("Immediate");
                   } else {
                        trigger_text = $('<td>').text(trigger_type + "@" + trigger_value);
                   }


                    scene_row.append(scene_name);
                    scene_row.append(scene_command);
                    scene_row.append(scene_action);
                    scene_row.append(trigger_text);
                    scene_table.append(scene_row);
                }
                // Add a footer spans the entire table that shows the last time the page was updated,
                // set the color to black
            const footer = $('<tr>');
               const footer_text = $('<td>').text("Last Updated: " + new Date().toLocaleString());
            footer_text.attr("colspan", 4);
            footer_text.css("color", "black");
            footer.append(footer_text);
            scene_table.append(footer);
        },
        error: function (xhr, status, error) {
            // Set the footer text to red, but don't change the text
            var footer = $('#device_list_body tr:last-child');
            footer.css("color", "red");

        }
    });
}

$(document).ready(scene_table());

// Make the above code run every 5 seconds without refreshing the page

setInterval(scene_table, 10000);