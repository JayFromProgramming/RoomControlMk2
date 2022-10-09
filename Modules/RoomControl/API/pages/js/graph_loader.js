
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
            option.selected = true;
            source_select.appendChild(option);
        }
    });

    // Set the start date to 24 hours ago
    // And the end date to now (Must conform to YYYY-MM-DD, the date must have leading zeros eg 2020-01-01)
    let start_date = new Date();
    let end_date = new Date();
    start_date.setDate(start_date.getDate() - 1);
    let date_str = start_date.getDate().toString().padStart(2, "0");
    let start_date_string = start_date.getFullYear() + "-" + (start_date.getMonth() + 1) + "-" + date_str;
    date_str = end_date.getDate().toString().padStart(2, "0");
    let end_date_string = end_date.getFullYear() + "-" + (end_date.getMonth() + 1) + "-" + date_str;

    document.getElementById("start_date").value = start_date_string;
    document.getElementById("start_time").value = start_date.toTimeString().split(" ")[0];
    document.getElementById("end_date").value = end_date_string;
    document.getElementById("end_time").value = end_date.toTimeString().split(" ")[0];

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
        let start_date = document.getElementById("start_date").value;
        let start_time = document.getElementById("start_time").value;
        let start = new Date(start_date + " " + start_time);
        // Start needs to be in a timestamp format (seconds since epoch)
        start = new Date(start).getTime() / 1000;
        let end_date = document.getElementById("end_date").value;
        let end_time = document.getElementById("end_time").value;
        let end = new Date(end_date + " " + end_time);
        // End needs to be in a timestamp format (seconds since epoch)
        end = new Date(end).getTime() / 1000;
        let sources = document.getElementById("multi_source_select_box").selectedOptions;
        let datasets = [];
        let labels = new Set();

        // Each source needs a different easy to read color, this is used to generate the colors
        let color_index = 0;
        let colors = ["#FF0000", "#00FF00", "#0000FF", "#00FFFF", "#FF00FF", "#000000", "#FFFFFF"];

        let promises = [];
        // Note: Each source does not need to have the same amount of data points, so the labels need to be
        //       generated from all the sources and then lined up in the graph

        // Fetch the data for each source
        for (let source of sources) {
            promises.push(fetch_data_log(source.value, start, end));
        }

        // Once all the data has been fetched, generate the graph
        Promise.all(promises).then(data => {
            let datasets = [];
            let labels = new Set();
            for (let source_data of data) {
                let source = source_data["source"];
                let data_points = source_data["data_log"];
                let dataset = {
                    label: source,
                    data: [],
                    fill: false,
                    borderColor: colors[color_index],
                    backgroundColor: colors[color_index],
                    pointRadius: 0,
                    pointHitRadius: 5
                };
                color_index += 1;
                for (let data_point of data_points) {
                    let timestamp = data_point[0];
                    let value = data_point[1];
                    dataset["data"].push({x: timestamp, y: value});
                    labels.add(timestamp);
                }
                datasets.push(dataset);
            }
            labels = Array.from(labels).sort();
            chart.data.labels = labels;
            chart.data.datasets = datasets;
            chart.update();
        });
    });

}

$(document).ready(initialize_page());