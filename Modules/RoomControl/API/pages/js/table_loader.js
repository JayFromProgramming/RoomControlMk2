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

$(document).ready(function () {
    $.ajax({
        url: "/get_all",
        type: "GET",
        dataType: "json",
        success: function (data) {
            var devices = data.devices; // A dictionary of devices and their data
            var device_table = $('#device_list_body');
            console.log(devices);
               for (var device in devices) {
                    var device_data = devices[device];
                    var device_row = $('<tr>');
                    var device_name = $('<td>').text(getName(device));
                    var device_toggle = $('<td>').html(button("/set/" + device + "?on=false", "Toggle"));
                    var device_status = $('<td>').text(getState(device));
                    var device_health = $('<td>').html(getHealth(device));

                    device_row.append(device_name);
                    device_row.append(device_toggle);
                    device_row.append(device_status);
                    device_row.append(device_health);
                    device_table.append(device_row);
                }
        },
        error: function (xhr, status, error) {
            alert("Error: " + error.message);
        }
    });
});