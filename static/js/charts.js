/**
 * Chart.js helper functions for creating pie charts and bar charts
 */

function createPieChart(canvasId, labels, values, title) {
    const ctx = document.getElementById(canvasId);
    
    if (!ctx) {
        console.error(`Canvas element with id "${canvasId}" not found`);
        return null;
    }

    // Generate colors for pie chart
    const colors = generateColors(labels.length);

    return new Chart(ctx, {
        type: 'pie',
        data: {
            labels: labels,
            datasets: [{
                label: title,
                data: values,
                backgroundColor: colors.background,
                borderColor: colors.border,
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        padding: 10,
                        font: {
                            size: 11
                        }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const label = context.label || '';
                            const value = context.parsed || 0;
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = ((value / total) * 100).toFixed(1);
                            return `${label}: ₹${value.toFixed(2)} (${percentage}%)`;
                        }
                    }
                }
            }
        }
    });
}

/**
 * Generate colors for pie chart slices
 */
function generateColors(count) {
    // Distinct hues for pie slices (easy to tell apart); not tied to app brown theme
    const baseColors = [
        'rgba(59, 130, 246, 0.88)',   // blue
        'rgba(244, 63, 94, 0.88)',    // rose
        'rgba(16, 185, 129, 0.88)',   // emerald
        'rgba(245, 158, 11, 0.88)',   // amber
        'rgba(139, 92, 246, 0.88)',   // violet
        'rgba(236, 72, 153, 0.88)',   // pink
        'rgba(6, 182, 212, 0.88)',    // cyan
        'rgba(234, 88, 12, 0.88)',    // orange
        'rgba(99, 102, 241, 0.88)',   // indigo
        'rgba(132, 204, 22, 0.88)',   // lime
        'rgba(168, 85, 247, 0.88)',   // purple
        'rgba(20, 184, 166, 0.88)',   // teal
        'rgba(251, 113, 133, 0.88)',  // light red
        'rgba(45, 212, 191, 0.88)',   // aqua
        'rgba(250, 204, 21, 0.88)',   // yellow
        'rgba(217, 70, 239, 0.88)'    // fuchsia
    ];

    const toSolidBorder = (rgba) => rgba.replace(/,\s*[\d.]+\)$/, ', 1)');

    const backgrounds = [];
    const borders = [];

    for (let i = 0; i < count; i++) {
        const color = baseColors[i % baseColors.length];
        backgrounds.push(color);
        borders.push(toSolidBorder(color));
    }

    return {
        background: backgrounds,
        border: borders
    };
}

/**
 * Create a bar chart
 */
function createBarChart(canvasId, labels, values, title, color = 'rgba(134, 75, 47, 0.8)') {
    const ctx = document.getElementById(canvasId);
    
    if (!ctx) {
        console.error(`Canvas element with id "${canvasId}" not found`);
        return null;
    }

    return new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: title,
                data: values,
                backgroundColor: color,
                borderColor: color.replace('0.8', '1'),
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const value = context.parsed.y || 0;
                            return '₹' + value.toFixed(2);
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: function(value) {
                            return '₹' + value.toFixed(0);
                        }
                    }
                }
            }
        }
    });
}

