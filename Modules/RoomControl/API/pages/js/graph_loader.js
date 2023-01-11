
// Generate a line graph of the selected data values, there can be multiple data sources selected
// And the will be graphed on the same graph, the available data sources are determined via the /get_data_log_source
// API endpoint and the data is retrieved via the /get_data_log/{source}/{start}/{end} API endpoint

// The graph is generated using the Chart.js library

class PresetSelector {

    constructor(presets, chart) {
        this.presets = presets["presets"];
        this.chart = chart;
        console.log(this.presets);
        this.preset_selector = document.getElementById("preset_selector");
        this.generate_graph_button = document.getElementById("generate_graph_button");
        this.selectedIndex = 0;
        for (let preset in this.presets) {
            let option = document.createElement("option");
            option.text = preset;
            this.preset_selector.add(option);
        }

        this.onSelectChange(0);

        this.preset_selector.onchange = this.onSelectChange.bind(this);

        this.generate_graph_button.onclick = this.onGenerateGraph.bind(this);

    }

    onSelectChange(event) {
        for (let i = 0; i < this.preset_selector.length; i++) {
            if (this.preset_selector[i].selected) {
                this.preformSelectChange(i);
                this.selectedIndex = i;
            }
        }
    }

    preformSelectChange(index) {

        const selectedPreset = this.preset_selector[index].value;
        const preset = this.presets[selectedPreset];

        let start_date = new Date();
        let end_date = new Date();
        const default_range = preset["time_range"];
        start_date.setSeconds(start_date.getSeconds() - default_range);
        end_date.setHours(end_date.getHours() + 1);

        const override_selected = document.getElementById("time_override");
        if (!override_selected.checked) {
            let date_str = start_date.getDate().toString().padStart(2, "0");
            let date_month = (start_date.getMonth() + 1).toString().padStart(2, "0");
            let start_date_string = start_date.getFullYear() + "-" + date_month + "-" + date_str;
            date_str = end_date.getDate().toString().padStart(2, "0");
            date_month = (end_date.getMonth() + 1).toString().padStart(2, "0");
            let end_date_string = end_date.getFullYear() + "-" + date_month + "-" + date_str;

            document.getElementById("start_date").value = start_date_string;
            document.getElementById("end_date").value = end_date_string;
            document.getElementById("start_time").value = start_date.toTimeString().split(" ")[0];
            document.getElementById("end_time").value = end_date.toTimeString().split(" ")[0];
        }

    }

    onGenerateGraph() {
        const selectedPreset = this.preset_selector[this.selectedIndex].value;
        const preset = this.presets[selectedPreset];

        const start_date = document.getElementById("start_date").value;
        const start_time = document.getElementById("start_time").value;
        const end_date = document.getElementById("end_date").value;
        const end_time = document.getElementById("end_time").value;

        const start = new Date(start_date + " " + start_time);
        const end = new Date(end_date + " " + end_time);

        const start_timestamp = start.getTime() / 1000;
        const end_timestamp = end.getTime() / 1000;

        const data_sources = preset["data_sources"];

        generate_graph(data_sources, start_timestamp, end_timestamp, this.chart);

    }

}

function fetch_data_log(source, start, end) {
    return fetch("/get_data_log/" + source + "/" + start + "/" + end)
        .then(response => response.json());
}

function fetch_data_log_sources() {
    return fetch("/get_data_log_sources")
        .then(response => response.json());
}

function generate_graph(sources, start, end, chart) {

    let datasets = [];
    let labels = new Set();

    // Each source needs a different easy to read color, this is used to generate the colors
    let color_index = 0;
    let colors = ["#FF0000", "#00FF00", "#0000FF", "#00FFFF", "#FF00FF", "#000000", "#FFFFFF"];
    let grey = "#808080";

    let promises = [];
    // Note: Each source does not need to have the same amount of data points, so the labels need to be
    //       generated from all the sources and then lined up in the graph

    // Fetch the data for each source
    for (let source of sources) {
        console.log(source);
        promises.push(fetch_data_log(source, start, end));
    }

    let all_time_stamps = new Set(); // Used to create a list of all the time stamps excluding duplicates

    const skipped = (ctx, value) => ctx.p0.skip || ctx.p1.skip ? value : undefined;


    // Once all the data has been fetched, generate the graph
    // If a source does not have data for a specific time stamp, then the value will be set to null
    Promise.all(promises).then(data => {
        console.log(data);
        for (let source_data of data) {
            // Get all the time stamps for each source and add them to the set
            console.log(source_data);
            for (let data_point of source_data["data_log"]) {
                all_time_stamps.add(data_point[0]); // Add the time stamp to the set
            }
        }

        let datasets = [];
        let labels = new Set();

        for (let source_data of data) {

            for (let timestamp of all_time_stamps) {
                // If the source does not have data for the time stamp, then set the value to null
                if (!source_data["data_log"].map(data_point => data_point[0]).includes(timestamp)) {
                    source_data["data_log"].push([timestamp, NaN]); // Add the time stamp with a null value
                }
            }
        }

        for (let source_data of data) {

            // Sort the data by the time stamp
            source_data["data_log"].sort((a, b) => a[0] - b[0]);

            // Add the data to the graph
            datasets.push({
                label: source_data["source"],
                data: source_data["data_log"].map(data_point => {
                    labels.add(data_point[0]);
                    return {
                        // Convert the time stamp to a date format string (not object, this is important)
                        x: data_point[0],
                        y: data_point[1]
                    }
                }),
                borderColor: colors[color_index],
                fill: false,
                pointRadius: 0,
                pointHitRadius: 5,
                segment: {
                    borderColor: ctx => skipped(ctx, grey),
                    borderDash: ctx => skipped(ctx, [6, 6])
                },
                spanGaps: true
            });

            color_index += 1;

        }

        // Convert the set of labels to an array and sort it
        labels = Array.from(labels);
        labels.sort();

        chart.data.labels = labels;
        chart.data.datasets = datasets;
        chart.update();
    });
}

function initialize_page() {


    // Set the start date to 24 hours ago
    // And the end date to now (Must conform to YYYY-MM-DD, the date must have leading zeros eg 2020-01-01)


    // Generate the blank graph, this will be updated when the user selects the "Generate Graph" button,
    // The Y axis will be updated to the correct dates
    let ctx = document.getElementById("graph_canvas").getContext("2d");

    let x_axis = {
        type: "time",
        time: {
            unit: "minute",
            parser: "X",
            tooltipFormat: "YYYY-MM-DD HH:mm:ss",
        },
        ticks: {
            source: "labels",
            autoSkip: true,
            autoSkipPadding: 20,
            maxRotation: 45,
        }
    };

    let y_axis = {
        type: "linear",
        ticks: {
            suggestedMin: 40,
            suggestedMax: 80,
        }
    }

    let chart = new Chart(ctx, {
        type: "line",
        data: {
            labels: [],
            datasets: []
        },
        options: {
            scales: {
                xAxes: [x_axis],
                yAxes: [y_axis]
            }
        }
    });

    fetch_data_log_sources().then(presets => {
        new PresetSelector(presets, chart);
    })

}

$(document).ready(initialize_page());