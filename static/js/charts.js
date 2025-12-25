/**
 * Chart.js helper functions for creating pie charts
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
                            return `${label}: $${value.toFixed(2)} (${percentage}%)`;
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
    const baseColors = [
        'rgba(54, 162, 235, 0.8)',  // Blue
        'rgba(255, 99, 132, 0.8)',  // Red
        'rgba(255, 206, 86, 0.8)',  // Yellow
        'rgba(75, 192, 192, 0.8)',  // Teal
        'rgba(153, 102, 255, 0.8)', // Purple
        'rgba(255, 159, 64, 0.8)',  // Orange
        'rgba(199, 199, 199, 0.8)', // Grey
        'rgba(83, 102, 255, 0.8)',  // Indigo
        'rgba(255, 99, 255, 0.8)',  // Pink
        'rgba(99, 255, 132, 0.8)',  // Green
        'rgba(255, 205, 86, 0.8)',  // Gold
        'rgba(54, 235, 162, 0.8)'   // Mint
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

