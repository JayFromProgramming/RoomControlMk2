
class ColorSelector {
  constructor(initialColor, device_id) {
    this.device_id = device_id;
    console.log("ColorSelector constructed");
    // Create a container for the color selector
    this.container = document.createElement('div');

    // Set the selected color and onUpdate function
    this.color = initialColor;

    // Create the color picker element
    const label = document.createElement('label');
    label.innerHTML = 'Color: ';
    this.container.appendChild(label);
    const input = document.createElement('input');
    input.type = 'color';
    input.value = this.color;
    input.addEventListener('input', this.handleInput.bind(this));

    // Add the color picker element to the container
    this.container.appendChild(input);
  }

  handleInput(event) {
    // Update the selected color and call the onUpdate function
    this.color = event.target.value;
    sendCommand(this.device_id, {"color": [parseInt(this.color.substring(1,3), 16),
     parseInt(this.color.substring(3,5), 16), parseInt(this.color.substring(5,7), 16)]});
  }

  updateData(json_data){
    var raw_color = json_data.state.color;
    // Convert the RGB array to a hex string
    this.color = '#' + raw_color[0].toString(16) + raw_color[1].toString(16) + raw_color[2].toString(16);
    // Update the color of the color picker
    this.container.querySelector('input').value = this.color;
  }

  getContainer() {
    // Return the container element
    return this.container;
  }
}