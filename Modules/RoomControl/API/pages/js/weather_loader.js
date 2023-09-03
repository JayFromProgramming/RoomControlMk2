
function KtoF (k) {
    return Math.round(((k - 273.15) * 1.8 + 32) * 10) / 10;
}

function mps_to_mph (mps) {
    return Math.round(mps * 2.23694);
}

function timestamp_to_time (ts) {
    var date = new Date(ts * 1000);
    var hours = date.getHours();
    var minutes = "0" + date.getMinutes();
    var seconds = "0" + date.getSeconds();
    return hours + ':' + minutes.substr(-2) + ':' + seconds.substr(-2);
}

function time_delta_to_stamp (timestamp, inverse = false) {
    // Create a time delta string from a timestamp
    // The delta is formatted as T-00:00 or T+00:00
    // The timestamp is in minutes

    var delta = timestamp - (Date.now() / 1000);
    var sign = '-';
    if (delta < 0 && !inverse) {
        sign = '+';
        delta = delta * -1;
    }
    var hours = Math.floor(delta / 3600);
    // Zero pad the hours to always be 2 digits
    hours = ('0' + hours).slice(-2);
    var minutes = Math.floor((delta - (hours * 3600)) / 60);
    return 'T' + sign + hours + ':' + minutes;
}

function visibility_to_string(visibility) {
    if (visibility < 10000){
        // Convert to miles if greater than 1 mile
        return Math.round((visibility / 1609) * 100) / 100 + ' mi';
    } else {
        return "Clear";
    }
}

function update_weather () {
    $.ajax({
        url: "/weather/now",
        type: "GET",
        dataType: "json",
        success: function (data) {
            var weather_box = $('#weather');
            weather_box.empty();
            weather_box.append('<table>');
            weather_box.append('<tr><td>Temperature:</td><td align="right"> '
                + KtoF(data["temperature"]['temp']) + '°F</td></tr>');
            weather_box.append('<tr><td>Feels Like:</td><td align="right"> '
                + KtoF(data["temperature"]['feels_like']) + '°F</td></tr>');
            weather_box.append('<tr><td>Humidity:</td><td align="right"> ' + data["humidity"] + '%</td></tr>');
            weather_box.append('<tr><td>Wind:</td><td align="right"> '
                + mps_to_mph(data["wind"]['speed']) + ' mph</td></tr>');
            weather_box.append('<tr><td>Clouds:</td><td align="right"> ' + data["clouds"] + '%</td></tr>');
            weather_box.append('<tr><td>Visibility:</td><td align="right"> ' +
                visibility_to_string(data["visibility_distance"]) + '</td></tr>');
            // For sunset and sunrise display only the one that is closest to the current time
            // And display a T- time under it
            if (data["sunrise"] > data["sunset"]) {
                weather_box.append('<tr><td>Sunrise:</td><td align="right"> ' +
                    timestamp_to_time(data["sunrise_time"]) +'\n' +
                    time_delta_to_stamp(data["sunrise_time"]) + '</td></tr>');
            } else {
                weather_box.append('<tr><td>Sunset:</td><td align="right"> ' +
                    timestamp_to_time(data["sunset_time"]) + '\n' +
                    time_delta_to_stamp(data["sunset_time"]) + '</td></tr>');
            }
            // Add a last updated timestamp
            weather_box.append('<tr><td>Last Update:</td><td align="right"> ' +
                timestamp_to_time(data["reference_time"]) + '</td></tr>');
            weather_box.append('</table>');
        }
     });
}

$(document).ready(update_weather());

// Update the weather every 1 minute
setInterval(update_weather, 60000);