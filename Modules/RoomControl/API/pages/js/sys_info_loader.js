

function device_table() {
    $.ajax({
        url: "/sys_info",
        type: "GET",
        dataType: "json",
        success: function (data) {
            sys_temp = data["sys_temp"];
            sys_cpu = data["sys_load"];
            sys_mem = data["sys_mem"];
            sys_uptime = data["sys_uptime"];

            var sys_info_box = $('#sys_info');
            sys_info_box.empty();
            sys_info_box.append('<table>');
            sys_info_box.append('<tr span=2><td>System Temperature</td><td>');

            if (sys_temp == null) {
                sys_info_box.append('<tr><td>CPU Temp:</td><td>N/A</td></tr>');
            }else {
                sys_info_box.append('<tr><td>CPU Temp:</td><td> ' + sys_temp + '°C</td></tr>');
            }


            sys_info_box.append('<tr><td>CPU Usage:</td><td> ' + sys_cpu + '%</td></tr>');
            sys_info_box.append('<tr><td>Mem Usage:</td><td> ' + sys_mem + '%</td></tr>');
            sys_info_box.append('<tr><td>Uptime:</td><td> ' + new Date(sys_uptime * 1000).toISOString().substr(11, 8) + '</td></tr>');
            sys_info_box.append('</table>');
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