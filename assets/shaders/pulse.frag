#version 150
uniform vec4 tint;
uniform float pulse;
out vec4 p3d_FragColor;
void main() {
    float gain = 0.35 + 0.65 * clamp(pulse, 0.0, 1.0);
    p3d_FragColor = vec4(tint.rgb * gain, tint.a);
}
