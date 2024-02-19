

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
            prog_uptime = data["prog_uptime"];

            var sys_info_box = $('#sys_info');
            sys_info_box.empty();
            sys_info_box.append('<table>');
            sys_info_box.append('<tr><td colspan=2 align="center">System Information</td><td>');

            if (sys_temp == null) {
                sys_info_box.append('<tr><td>CPU Temp:</td><td align="right">N/A</td></tr>');
            }else {
                sys_info_box.append('<tr><td>CPU Temp:</td><td align="right"> ' + sys_temp + '°C</td></tr>');
            }


            sys_info_box.append('<tr><td>CPU Load:</td><td align="right"> ' + sys_cpu + '%</td></tr>');
            sys_info_box.append('<tr><td>Mem Usage:</td><td align="right"> ' + sys_mem + '%</td></tr>');
            sys_info_box.append('<tr><td>Sys  Uptime: </td><td align="right"> ' + new Date(sys_uptime * 1000).toISOString().substr(11, 8) + '</td></tr>');
            sys_info_box.append('<tr><td>Prog Uptime: </td><td align="right"> ' + new Date(prog_uptime * 1000).toISOString().substr(11, 8) + '</td></tr>');
            sys_info_box.append('</table>');
        },
        error: function (xhr, status, error) {

        }
    });
}

$(document).ready(device_table());

// Make the above code run every 5 seconds without refreshing the page

setInterval(device_table, 5000);