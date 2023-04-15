
class ColorSelector {
    constructor(initialColor, device_id) {
        this.device_id = device_id;
        console.log("ColorSelector constructed");
        // Create a container for the color selector
        this.container = document.createElement('div');

        // Set the selected color and onUpdate function
        this.color = initialColor;
        this.brightness = 255;
        this.white = false;

        // Create a value to store an internal rate limit
        this.last_update = 0;

        // Create the color picker element
        const label = document.createElement('label');
        const color_input = document.createElement('input');
        const enable_white = document.createElement('button');  // This is a boolean value setup for RGBW lights to enable the white channel
        const brightness_slider = document.createElement('input');  // This is a slider to control the brightness of the light
        label.innerHTML = 'Color: ';
        this.container.appendChild(label);
        color_input.type = 'color';
        color_input.id = 'color_input';
        color_input.value = this.color;
        this.container.appendChild(color_input);
        enable_white.type = 'checkbox';
        enable_white.innerHTML = 'Enable White';
        enable_white.value = this.white;
        enable_white.id = 'enable_white';
        this.container.appendChild(enable_white);
        brightness_slider.type = 'range';
        brightness_slider.min = '0';
        brightness_slider.max = '255';
        brightness_slider.value = this.brightness;
        brightness_slider.id = 'brightness_slider';
        this.container.appendChild(brightness_slider);
        // Add the event listeners
        color_input.addEventListener('input', this.handleColorInput.bind(this));
        enable_white.addEventListener('click', this.handleWhiteInput.bind(this));
        brightness_slider.addEventListener('input', this.handleBrightnessInput.bind(this));

    }

    handleColorInput(event) {
    // Update the selected color and call the onUpdate function
        console.log("ColorSelector handleColorInput");
        this.color = event.target.value;
        if (this.last_update + 100 > Date.now()) {
            return;
        }
        sendCommand(this.device_id, {"color": [parseInt(this.color.substring(1,3), 16),
        parseInt(this.color.substring(3,5), 16), parseInt(this.color.substring(5,7), 16)]});
        this.last_update = Date.now();
    }

    handleWhiteInput(event) {
        // Update the selected color and call the onUpdate function
        sendCommand(this.device_id, {"white_enabled": true, "white": this.brightness * 1});
    }

    handleBrightnessInput(event) {
        console.log("Brightness input");
        // Update the selected color and call the onUpdate function
        this.brightness = event.target.value;
        sendCommand(this.device_id, {"brightness": this.brightness * 1});
    }

    updateData(json_data){
        var raw_color = json_data.state.color;
        var raw_white = json_data.state.white_enabled;
        var raw_brightness = json_data.state.brightness;
        // Convert the RGB array to a hex string
        this.color = '#' + raw_color[0].toString(16).padStart(2, '0') + raw_color[1].toString(16).padStart(2, '0')
        + raw_color[2].toString(16).padStart(2, '0');
        this.white = raw_white;
        this.brightness = raw_brightness;
        // Update the color of the color picker
        this.container.querySelector('#color_input').value = this.color;
        this.container.querySelector('#enable_white').value = this.white;
        this.container.querySelector('#brightness_slider').value = this.brightness;

    }

  getContainer() {
    // Return the container element
    return this.container;
  }
}

class ToggleSwitch{
    constructor(initialState, device_id) {
        this.device_id = device_id;
        console.log("ToggleSwitch constructed");
        // Create a container for the toggle switch
        this.container = document.createElement('div');

        // Set the selected state and onUpdate function
        this.state = initialState;

        // Create the toggle switch element
        const label = document.createElement('label');
        const toggle_switch = document.createElement('input');
        label.innerHTML = 'Enabled: ';
        this.container.appendChild(label);
        toggle_switch.type = 'checkbox';
        toggle_switch.id = 'toggle_switch';
        toggle_switch.checked = this.state;
        this.container.appendChild(toggle_switch);
        // Add the event listener
        toggle_switch.addEventListener('click', this.handleToggleSwitch.bind(this));
    }

    handleToggleSwitch(event) {
        // Update the selected state and call the onUpdate function
        console.log("ToggleSwitch handleToggleSwitch");
        this.state = event.target.checked;
        sendCommand(this.device_id, {"on": this.state});
    }

    updateData(json_data){
        this.state = json_data.state.on;
        // Update the state of the toggle switch
        this.container.querySelector('#toggle_switch').checked = this.state;
    }

    getContainer() {
        // Return the container element
        return this.container;
    }
}

class SetpointSelector {
    constructor(initialSetpoint, device_id, unit) {
        this.device_id = device_id;
        console.log("SetpointSelector constructed");
        // Create a container for the setpoint selector
        this.container = document.createElement('div');

        // Set the selected setpoint and onUpdate function
        this.setpoint = initialSetpoint;
        this.unit = unit;

        // Create the setpoint selector element
        const label = document.createElement('label');
        const setpoint_input = document.createElement('input');
        const unit_label = document.createElement('label');
        const submit_button = document.createElement('button');
        label.innerHTML = 'Setpoint: ';
        this.container.appendChild(label);
        setpoint_input.type = 'number';
        setpoint_input.id = 'setpoint_input';
        setpoint_input.value = this.setpoint;
        // Set max width to 50px
        setpoint_input.style.maxWidth = '50px';
        this.container.appendChild(setpoint_input);
        unit_label.innerHTML = this.unit;
        this.container.appendChild(unit_label);
        submit_button.innerHTML = 'Submit';
        this.container.appendChild(submit_button);
        // Add the event listener
        submit_button.addEventListener('click', this.handleSetpointInput.bind(this));
    }

    handleSetpointInput(event) {
        // Update the selected setpoint and call the onUpdate function
        console.log("SetpointSelector handleSetpointInput");
        this.setpoint = this.container.querySelector('#setpoint_input').value;
        sendCommand(this.device_id, {"target_value": this.setpoint * 1});
    }

    updateData(json_data){
        // Check if the setpoint box is currently in focus, if so, don't update the setpoint
        if (document.activeElement.id == 'setpoint_input') {
            return;
        }
        this.setpoint = json_data.state.target_value;
        // Update the setpoint of the setpoint selector
        this.container.querySelector('#setpoint_input').value = this.setpoint;
    }

    getContainer() {
        // Return the container element
        return this.container;
    }

}