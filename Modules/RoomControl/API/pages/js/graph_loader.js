
// Generate a line graph of the selected data values, there can be multiple data sources selected
// And the will be graphed on the same graph, the available data sources are determined via the /get_data_log_source
// API endpoint and the data is retrieved via the /get_data_log/{source}/{start}/{end} API endpoint

// The graph is generated using the Chart.js library

function fetch_data_log(source, start, end) {
    return fetch("/get_data_log/" + source + "/" + start + "/" + end)
        .then(response => response.json());
}

function fetch_data_log_sources() {
    return fetch("/get_data_log_sources")
        .then(response => response.json());
}

function initialize_page() {
    fetch_data_log_sources().then(sources => {
        let source_select = document.getElementById("multi_source_select_box");
        for (let source of sources["data_log_sources"]) {
            let option = document.createElement("option");
            option.value = source;
            option.text = source;
            source_select.appendChild(option);
        }
    });

    // Set the start date to 24 hours ago
    // And the end date to now (Must conform to YYYY-MM-DD, the date must have leading zeros eg 2020-01-01)
    let start_date = new Date();
    start_date.setHours(start_date.getHours() - 24);
    let end_date = new Date();
    end_date.setHours(end_date.getHours() + 25);
    let date_str = start_date.getDate().toString().padStart(2, "0");
    let start_date_string = start_date.getFullYear() + "-" + (start_date.getMonth() + 1) + "-" + date_str;
    date_str = end_date.getDate().toString().padStart(2, "0");
    let end_date_string = end_date.getFullYear() + "-" + (end_date.getMonth() + 1) + "-" + date_str;

    document.getElementById("start_date").value = start_date_string;
    document.getElementById("end_date").value = end_date_string;

    // Generate the blank graph, this will be updated when the user selects the "Generate Graph" button,
    // The Y axis will be updated to the correct dates
    let ctx = document.getElementById("graph_canvas").getContext("2d");
    let chart = new Chart(ctx, {
        type: "line",
        data: {
            labels: [],
            datasets: []
        }
    });

    // Add the event listener to the "Generate Graph" button
    document.getElementById("generate_graph_button").addEventListener("click", () => {
        let start = document.getElementById("start_date").value;
        // Start needs to be in a timestamp format (seconds since epoch)
        start = new Date(start).getTime() / 1000;
        let end = document.getElementById("end_date").value;
        // End needs to be in a timestamp format (seconds since epoch)
        end = new Date(end).getTime() / 1000;
        let sources = document.getElementById("multi_source_select_box").selectedOptions;
        let datasets = [];
        let labels = [];

        // Each source needs a different easy to read color, this is used to generate the colors
        let color_index = 0;
        let colors = ["#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#00FFFF", "#FF00FF", "#000000", "#FFFFFF"];

        let promises = [];
        for (let source of sources) {
            promises.push(fetch_data_log(source.value, start, end).then(data => {
                datasets.push({
                    label: source.value,
                    // Data is returned as a list of (timestamp, value) pairs so we need to extract the values
                    data: data["data_log"].map(x => x[1]),
                    fill: false,
                    borderColor: colors[color_index],
                });
                color_index += 1;
                // Add timestamps to the labels, we will convert them to a human readable format later
                labels = data["data_log"].map(x => x[0]);
            }));
        }
        Promise.all(promises).then(() => {
            chart.data.datasets = datasets;
            chart.data.labels = labels;

            // Convert the timestamps to a human readable format
            // This is done by overriding the default tick generation function

            // chart.options = {
            //     scales: {
            //         xAxes: [{
            //             ticks: {
            //                 callback: function (value, index, values) {
            //                     return new Date(value * 1000).toLocaleString();
            //                 }
            //             }
            //         }]
            //     }
            // }

            // Adjust the Y axis scaling to fit the data but not be too zoomed in (Minimum view range is 10 units)
            chart.update();
        });
    });

}

$(document).ready(initialize_page());