class DeviceList {
    constructor(starting_device, selection_changed_callback) {
        this.devices = [];
        this.selected_device = null;
        this.container = document.createElement('div');
        this.container.id = "device_list";
        this.label = document.createElement('label');
        this.last_updated_label = document.createElement('label');
        this.label.innerHTML = "Select a device:  ";
        // Add a line at the bottom of the div and a bit of padding
        this.container.style.borderBottom = "1px solid #000000";
        this.container.style.paddingBottom = "5px";

        this.last_updated_label.id = "last_updated_label";
        this.last_updated_label.innerHTML = "Last updated: ";
        // Set the last updated label to be on the right
        this.last_updated_label.style.float = "right";

        this.container.appendChild(this.label);
        this.list_element = document.createElement('select');
        this.container.appendChild(this.list_element);
        this.container.appendChild(this.last_updated_label);
        this.selection_changed_callback = selection_changed_callback; // Callback function to be called when the selected device changes
        this.loadDevices();
        this.container.addEventListener('click', this.handleDeviceClick.bind(this));
        if (starting_device !== null) {
            console.log("Selecting device: " + starting_device);
            this.selectDevice(starting_device);
        }
    }

    selectDevice(device_id) {
        // Select a device
        this.list_element.value = device_id;
        if (typeof this.selection_changed_callback === 'function') {
            this.selected_device = device_id;
            this.selection_changed_callback(device_id);
        } else {
            console.log("No callback function set");
        }
    }

    handleDeviceClick(event) {
        // Check if the selected device changed and if so fire the callback
        var device_id = this.list_element.value;
        if (device_id !== this.selected_device) {
            this.selectDevice(device_id);
        }
    }

    loadDevices() {
        // Load the list of devices from the server
        $.ajax({
            url: '/get_all',
            type: 'GET',
            dataType: 'json',
            outer: this,
            async: false,
            success: function(data) {
                // Create a list entry for each device (Do not create a DeviceObject)
                for (var device_id in data.devices) {
//                     console.log(device_id);
                    var device_name = getName(device_id);
                    var device_type = data.devices[device_id].type;
                    var device_element = document.createElement('option');
                    device_element.value = device_id;
                    device_element.innerHTML = device_name;
                    this.outer.list_element.appendChild(device_element);
                }
            }
        });
    }

    getContainer() {
        // Return the container element
        return this.container;
    }

    device_updated(){
        this.last_updated_label.innerHTML = "Last updated: " + new Date().toLocaleString();
    }

}