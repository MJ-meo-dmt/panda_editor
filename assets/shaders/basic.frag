#version 150
uniform vec4 tint;
in vec4 v_color;
out vec4 p3d_FragColor;
void main() {
    p3d_FragColor = v_color * tint;
}
