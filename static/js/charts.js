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
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        padding: 15,
                        font: {
                            size: 12
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
    // Updated color palette with better contrast and modern colors
    const baseColors = [
        'rgba(99, 102, 241, 0.8)',  // Indigo
        'rgba(236, 72, 153, 0.8)',  // Pink
        'rgba(14, 165, 233, 0.8)',  // Sky Blue
        'rgba(34, 197, 94, 0.8)',   // Green
        'rgba(251, 146, 60, 0.8)',  // Orange
        'rgba(168, 85, 247, 0.8)',  // Purple
        'rgba(59, 130, 246, 0.8)',  // Blue
        'rgba(239, 68, 68, 0.8)',   // Red
        'rgba(234, 179, 8, 0.8)',   // Yellow
        'rgba(20, 184, 166, 0.8)',  // Teal
        'rgba(249, 115, 22, 0.8)',  // Orange Red
        'rgba(139, 92, 246, 0.8)'   // Violet
    ];

    const backgrounds = [];
    const borders = [];

    for (let i = 0; i < count; i++) {
        const color = baseColors[i % baseColors.length];
        backgrounds.push(color);
        // Darker version for border
        borders.push(color.replace('0.8', '1'));
    }

    return {
        background: backgrounds,
        border: borders
    };
}

/**
 * Create a bar chart
 */
function createBarChart(canvasId, labels, values, title, color = 'rgba(54, 162, 235, 0.8)') {
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

