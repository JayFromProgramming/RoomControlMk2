
function sendCommand(device_id, commands) {
    // Endpoint /set/{name} expects a POST request with a JSON body
    // The JSON body should be a dictionary with the key being the value of target and the value being the value of value
    $.ajax({
        url: "/set/" + device_id,
        type: "POST",
        data: JSON.stringify(commands),
        contentType: "application/json; charset=utf-8",
        dataType: "json",
        success: function(data) {
            console.log("Success: " + data);
        },
        failure: function(errMsg) {
            console.log("Error: " + errMsg);
        }
    });
}