document.addEventListener('DOMContentLoaded', () => {
    // ==========================================================================
    // 1. Navigation & Scroll Effects
    // ==========================================================================
    const navbar = document.querySelector('.navbar');
    window.addEventListener('scroll', () => {
        if (window.scrollY > 50) {
            navbar.classList.add('scrolled');
        } else {
            navbar.classList.remove('scrolled');
        }
    });

    // Mobile Navigation Toggle
    const mobileNavToggle = document.querySelector('.mobile-nav-toggle');
    const mobileDrawer = document.querySelector('.mobile-drawer');
    const drawerLinks = document.querySelectorAll('.drawer-link');

    const toggleMenu = () => {
        mobileNavToggle.classList.toggle('open');
        mobileDrawer.classList.toggle('open');
        document.body.style.overflow = mobileDrawer.classList.contains('open') ? 'hidden' : '';
    };

    mobileNavToggle.addEventListener('click', toggleMenu);
    drawerLinks.forEach(link => {
        link.addEventListener('click', () => {
            if (mobileDrawer.classList.contains('open')) {
                toggleMenu();
            }
        });
    });

    // ==========================================================================
    // 2. Scroll Reveal Animations (Intersection Observer)
    // ==========================================================================
    const revealElements = document.querySelectorAll('.scroll-reveal');
    const revealObserver = new IntersectionObserver((entries, observer) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('revealed');
                observer.unobserve(entry.target);
            }
        });
    }, {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    });

    revealElements.forEach(el => revealObserver.observe(el));

    // ==========================================================================
    // 3. Tab Switcher (Integration Showcase)
    // ==========================================================================
    const tabButtons = document.querySelectorAll('.tab-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');

    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetTab = btn.getAttribute('data-tab');

            tabButtons.forEach(b => b.classList.remove('active'));
            tabPanes.forEach(p => p.classList.remove('active'));

            btn.classList.add('active');
            document.getElementById(`tab-${targetTab}`).classList.add('active');
        });
    });

    // ==========================================================================
    // 4. Chart Toggle (Benchmark Section)
    // ==========================================================================
    const toggleButtons = document.querySelectorAll('.toggle-btn');
    const barGroups = document.querySelectorAll('.comparison-bar-group');

    toggleButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetChart = btn.getAttribute('data-target');

            toggleButtons.forEach(b => b.classList.remove('active'));
            barGroups.forEach(g => g.classList.remove('active'));

            btn.classList.add('active');
            document.getElementById(`chart-${targetChart}`).classList.add('active');
        });
    });

    // ==========================================================================
    // 5. Clipboard Copy Helper
    // ==========================================================================
    const copyButtons = document.querySelectorAll('.copy-btn');
    copyButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const codeBlock = btn.nextElementSibling.querySelector('code');
            const textToCopy = codeBlock.textContent;

            navigator.clipboard.writeText(textToCopy).then(() => {
                btn.textContent = 'Copied!';
                btn.classList.add('copied');

                setTimeout(() => {
                    btn.textContent = 'Copy';
                    btn.classList.remove('copied');
                }, 2000);
            }).catch(err => {
                console.error('Failed to copy text: ', err);
            });
        });
    });

    // ==========================================================================
    // 6. Interactive Canvas Particle Background
    // ==========================================================================
    const particleCanvas = document.getElementById('particle-canvas');
    const pCtx = particleCanvas.getContext('2d');
    let particles = [];
    const particleCount = window.innerWidth < 768 ? 40 : 80;

    const resizeParticleCanvas = () => {
        particleCanvas.width = window.innerWidth;
        particleCanvas.height = window.innerHeight;
    };
    resizeParticleCanvas();
    window.addEventListener('resize', resizeParticleCanvas);

    class Particle {
        constructor() {
            this.x = Math.random() * particleCanvas.width;
            this.y = Math.random() * particleCanvas.height;
            this.vx = (Math.random() - 0.5) * 0.3;
            this.vy = (Math.random() - 0.5) * 0.3;
            this.radius = Math.random() * 2 + 1;
            this.alpha = Math.random() * 0.5 + 0.1;
        }

        update() {
            this.x += this.vx;
            this.y += this.vy;

            if (this.x < 0 || this.x > particleCanvas.width) this.vx *= -1;
            if (this.y < 0 || this.y > particleCanvas.height) this.vy *= -1;
        }

        draw() {
            pCtx.beginPath();
            pCtx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
            pCtx.fillStyle = `rgba(139, 92, 246, ${this.alpha})`;
            pCtx.fill();
        }
    }

    for (let i = 0; i < particleCount; i++) {
        particles.push(new Particle());
    }

    const animateParticles = () => {
        pCtx.clearRect(0, 0, particleCanvas.width, particleCanvas.height);
        
        particles.forEach(p => {
            p.update();
            p.draw();
        });

        // Draw connections
        for (let i = 0; i < particles.length; i++) {
            for (let j = i + 1; j < particles.length; j++) {
                const dist = Math.hypot(particles[i].x - particles[j].x, particles[i].y - particles[j].y);
                if (dist < 120) {
                    const alpha = (1 - dist / 120) * 0.15;
                    pCtx.beginPath();
                    pCtx.moveTo(particles[i].x, particles[i].y);
                    pCtx.lineTo(particles[j].x, particles[j].y);
                    pCtx.strokeStyle = `rgba(6, 182, 212, ${alpha})`;
                    pCtx.lineWidth = 0.5;
                    pCtx.stroke();
                }
            }
        }

        requestAnimationFrame(animateParticles);
    };
    animateParticles();


    // ==========================================================================
    // 7. Hero Section - Codebase Engine Visualizer Canvas
    // ==========================================================================
    const visualizerCanvas = document.getElementById('visualizer-canvas');
    const vCtx = visualizerCanvas.getContext('2d');
    let visualizerWidth, visualizerHeight;

    const resizeVisualizerCanvas = () => {
        const rect = visualizerCanvas.getBoundingClientRect();
        visualizerCanvas.width = rect.width * window.devicePixelRatio;
        visualizerCanvas.height = rect.height * window.devicePixelRatio;
        vCtx.scale(window.devicePixelRatio, window.devicePixelRatio);
        visualizerWidth = rect.width;
        visualizerHeight = rect.height;
    };
    
    // Initial size setup
    setTimeout(resizeVisualizerCanvas, 100);
    window.addEventListener('resize', resizeVisualizerCanvas);

    // Animation Steps control
    let currentStep = 1;
    let stepTimer = 0;
    const stepDuration = 180; // 3 seconds per step at 60fps
    const stepOverlayElements = {
        1: document.querySelector('.flow-step.step-1'),
        2: document.querySelector('.flow-step.step-2'),
        3: document.querySelector('.flow-step.step-3'),
        4: document.querySelector('.flow-step.step-4')
    };

    // Visualization Entities
    let files = [];
    let vectors = [];
    let chunks = [];
    let scanLineY = 0;
    let scanDirection = 1;
    let highlightDotIndex = -1;
    let activeCardOpacity = 0;

    // Initialize visualizer assets
    const initVisualizerEntities = () => {
        // Files representation (Step 1)
        files = [];
        const fileNames = ['main.py', 'setup.py', 'src/search.py', 'src/mcp.py', 'src/index.py', 'requirements.txt', 'config.yaml'];
        const startX = 60;
        const startY = 80;
        fileNames.forEach((name, idx) => {
            files.push({
                name,
                x: startX,
                y: startY + idx * 32,
                alpha: 0,
                selected: false
            });
        });

        // Chunks floating down (Step 2)
        chunks = [];
        for (let i = 0; i < 15; i++) {
            chunks.push({
                x: 100 + Math.random() * 200,
                y: 100 + Math.random() * 100,
                radius: Math.random() * 4 + 2,
                color: Math.random() > 0.5 ? 'var(--primary)' : 'var(--secondary)',
                speed: 1 + Math.random() * 1.5,
                alpha: 0
            });
        }

        // Vectors in space (Step 3 & 4)
        vectors = [];
        for (let i = 0; i < 30; i++) {
            vectors.push({
                x: 220 + Math.random() * 120,
                y: 120 + Math.random() * 120,
                originalX: 220 + Math.random() * 120,
                originalY: 120 + Math.random() * 120,
                radius: Math.random() * 3 + 1.5,
                color: 'var(--primary)',
                glowing: false,
                alpha: 0.3
            });
        }
    };
    initVisualizerEntities();

    const drawStep1 = () => {
        // Step 1: Draw File System Trees
        vCtx.font = '11px JetBrains Mono';
        vCtx.fillStyle = 'rgba(255, 255, 255, 0.4)';
        vCtx.fillText('📂 Workspace: /FourTIndex', 40, 50);

        files.forEach((file, idx) => {
            file.alpha = Math.min(1, file.alpha + 0.05);
            vCtx.fillStyle = `rgba(255, 255, 255, ${file.alpha * 0.8})`;
            
            // Draw directory branches
            vCtx.strokeStyle = 'rgba(255, 255, 255, 0.1)';
            vCtx.lineWidth = 1;
            vCtx.beginPath();
            vCtx.moveTo(48, file.y - 6);
            vCtx.lineTo(56, file.y - 6);
            vCtx.stroke();
            if (idx === 0) {
                vCtx.beginPath();
                vCtx.moveTo(48, 52);
                vCtx.lineTo(48, files[files.length - 1].y - 6);
                vCtx.stroke();
            }

            vCtx.fillText(`📄 ${file.name}`, file.x, file.y);
            
            // Draw dummy code lines next to file name
            vCtx.fillStyle = 'rgba(139, 92, 246, 0.15)';
            vCtx.fillRect(file.x + 120, file.y - 8, 40 + Math.random() * 30, 6);
        });
    };

    const drawStep2 = () => {
        // Step 2: Show parsing file content to chunks
        drawStep1(); // Keep files in background

        // Draw an "AST Parser" funnel / boundary
        vCtx.strokeStyle = 'rgba(6, 182, 212, 0.2)';
        vCtx.lineWidth = 1;
        vCtx.strokeRect(170, 70, 80, 200);
        vCtx.fillStyle = 'rgba(6, 182, 212, 0.03)';
        vCtx.fillRect(170, 70, 80, 200);

        vCtx.font = '10px Plus Jakarta Sans';
        vCtx.fillStyle = 'rgba(6, 182, 212, 0.7)';
        vCtx.fillText('Tree-Sitter', 183, 90);
        vCtx.fillText('Parser', 195, 105);

        // Animate scanning line inside the parser
        scanLineY += scanDirection * 1.5;
        if (scanLineY > 180 || scanLineY < 0) scanDirection *= -1;
        
        vCtx.strokeStyle = 'var(--secondary)';
        vCtx.lineWidth = 1.5;
        vCtx.beginPath();
        vCtx.moveTo(170, 80 + scanLineY);
        vCtx.lineTo(250, 80 + scanLineY);
        vCtx.stroke();

        // Glowing effect on scan line
        const grad = vCtx.createLinearGradient(170, 80+scanLineY, 250, 80+scanLineY);
        grad.addColorStop(0, 'rgba(6, 182, 212, 0)');
        grad.addColorStop(0.5, 'rgba(6, 182, 212, 0.3)');
        grad.addColorStop(1, 'rgba(6, 182, 212, 0)');
        vCtx.fillStyle = grad;
        vCtx.fillRect(170, 80 + scanLineY - 8, 80, 16);

        // Chunks flying into the parser and transforming into embeddings
        chunks.forEach(chunk => {
            chunk.alpha = Math.min(1, chunk.alpha + 0.05);
            chunk.y += chunk.speed;
            if (chunk.y > 250) {
                chunk.y = 80;
                chunk.x = 180 + Math.random() * 60;
            }

            vCtx.beginPath();
            vCtx.arc(chunk.x, chunk.y, chunk.radius, 0, Math.PI * 2);
            vCtx.fillStyle = chunk.color;
            vCtx.shadowColor = chunk.color;
            vCtx.shadowBlur = 8;
            vCtx.fill();
            vCtx.shadowBlur = 0; // Reset
        });
    };

    const drawStep3 = () => {
        // Step 3: Draw Vector Clusters in Local DB
        vCtx.font = '11px JetBrains Mono';
        vCtx.fillStyle = 'rgba(255, 255, 255, 0.4)';
        vCtx.fillText('💿 ChromaDB (100% Local Vector Space)', 160, 50);

        // Draw connections between vector cluster points
        vCtx.strokeStyle = 'rgba(139, 92, 246, 0.08)';
        vCtx.lineWidth = 0.5;
        for (let i = 0; i < vectors.length; i++) {
            for (let j = i + 1; j < vectors.length; j++) {
                const d = Math.hypot(vectors[i].x - vectors[j].x, vectors[i].y - vectors[j].y);
                if (d < 45) {
                    vCtx.beginPath();
                    vCtx.moveTo(vectors[i].x, vectors[i].y);
                    vCtx.lineTo(vectors[j].x, vectors[j].y);
                    vCtx.stroke();
                }
            }
        }

        // Draw Vector points
        vectors.forEach(v => {
            vCtx.beginPath();
            vCtx.arc(v.x, v.y, v.radius, 0, Math.PI * 2);
            vCtx.fillStyle = 'rgba(139, 92, 246, 0.7)';
            vCtx.fill();
        });

        // Add subtle orbit or vibration to show DB is active
        vectors.forEach(v => {
            v.x = v.originalX + Math.sin(stepTimer * 0.02 + v.originalY) * 2;
            v.y = v.originalY + Math.cos(stepTimer * 0.02 + v.originalX) * 2;
        });
    };

    const drawStep4 = () => {
        // Step 4: Semantic Query search and extract compact code chunk
        drawStep3(); // Vector DB in the background

        // Query point originating from Agent
        const agentX = 60;
        const agentY = 160;

        vCtx.font = '10px JetBrains Mono';
        vCtx.fillStyle = 'var(--secondary)';
        vCtx.fillText('🤖 AI Agent Query', agentX - 10, agentY - 30);
        vCtx.fillStyle = '#fff';
        vCtx.fillText('"How is split batch implemented?"', agentX - 20, agentY - 14);

        // Agent node representation
        vCtx.beginPath();
        vCtx.arc(agentX, agentY, 12, 0, Math.PI * 2);
        vCtx.fillStyle = 'rgba(6, 182, 212, 0.2)';
        vCtx.strokeStyle = 'var(--secondary)';
        vCtx.lineWidth = 2;
        vCtx.fill();
        vCtx.stroke();

        // Select a point to highlight / match
        if (highlightDotIndex === -1) {
            highlightDotIndex = Math.floor(Math.random() * vectors.length);
        }
        const matchedDot = vectors[highlightDotIndex];

        // Animate radar beam from agent to matched point
        vCtx.strokeStyle = 'rgba(6, 182, 212, 0.4)';
        vCtx.setLineDash([4, 4]);
        vCtx.lineWidth = 1;
        vCtx.beginPath();
        vCtx.moveTo(agentX, agentY);
        vCtx.lineTo(matchedDot.x, matchedDot.y);
        vCtx.stroke();
        vCtx.setLineDash([]); // Reset

        // Draw pulsing halo on matched vector point
        const pulseRadius = 5 + Math.sin(stepTimer * 0.15) * 4;
        vCtx.beginPath();
        vCtx.arc(matchedDot.x, matchedDot.y, pulseRadius, 0, Math.PI * 2);
        vCtx.strokeStyle = 'var(--accent)';
        vCtx.lineWidth = 1.5;
        vCtx.stroke();

        vCtx.beginPath();
        vCtx.arc(matchedDot.x, matchedDot.y, 4, 0, Math.PI * 2);
        vCtx.fillStyle = 'var(--accent)';
        vCtx.fill();

        // Code window popup (Targeted snippet extraction)
        activeCardOpacity = Math.min(1, activeCardOpacity + 0.05);
        vCtx.save();
        vCtx.globalAlpha = activeCardOpacity;
        
        // Draw Glass Card
        vCtx.fillStyle = 'rgba(4, 5, 8, 0.9)';
        vCtx.strokeStyle = 'rgba(16, 185, 129, 0.4)';
        vCtx.lineWidth = 1.5;
        
        const cardX = 110;
        const cardY = 220;
        const cardW = 210;
        const cardH = 100;
        
        vCtx.fillRect(cardX, cardY, cardW, cardH);
        vCtx.strokeRect(cardX, cardY, cardW, cardH);

        // Highlight header
        vCtx.fillStyle = 'rgba(16, 185, 129, 0.1)';
        vCtx.fillRect(cardX, cardY, cardW, 20);
        vCtx.font = '9px JetBrains Mono';
        vCtx.fillStyle = 'var(--accent)';
        vCtx.fillText('✅ chunk_array_size() in main.py:L142', cardX + 8, cardY + 13);

        // Dummy Code content
        vCtx.fillStyle = 'rgba(255, 255, 255, 0.6)';
        vCtx.font = '8px JetBrains Mono';
        vCtx.fillText('def chunk_array_size(data, batch_size):', cardX + 12, cardY + 36);
        vCtx.fillText('    # Code snippet matches query conceptually!', cardX + 12, cardY + 48);
        vCtx.fillText('    return [data[i:i+batch_size]', cardX + 12, cardY + 60);
        vCtx.fillText('            for i in range(0, len(data), batch_size)]', cardX + 12, cardY + 72);

        // Savings badge
        vCtx.fillStyle = 'rgba(16, 185, 129, 0.15)';
        vCtx.fillRect(cardX + 120, cardY + 80, 80, 14);
        vCtx.fillStyle = 'var(--accent)';
        vCtx.font = 'bold 8px Plus Jakarta Sans';
        vCtx.fillText('14.7x SAVINGS', cardX + 128, cardY + 90);

        vCtx.restore();
    };

    const animateVisualizer = () => {
        if (!visualizerWidth || !visualizerHeight) {
            requestAnimationFrame(animateVisualizer);
            return;
        }

        vCtx.clearRect(0, 0, visualizerWidth, visualizerHeight);

        // Run animations based on current step
        stepTimer++;
        if (stepTimer >= stepDuration) {
            // Move to next step
            stepTimer = 0;
            
            // Remove active class from previous overlay
            stepOverlayElements[currentStep].classList.remove('active');
            
            currentStep = currentStep === 4 ? 1 : currentStep + 1;
            
            // Add active class to new overlay
            stepOverlayElements[currentStep].classList.add('active');

            // Reset entities states when loop restarts
            if (currentStep === 1) {
                initVisualizerEntities();
                highlightDotIndex = -1;
                activeCardOpacity = 0;
            }
        }

        // Draw standard components
        switch (currentStep) {
            case 1:
                drawStep1();
                break;
            case 2:
                drawStep2();
                break;
            case 3:
                drawStep3();
                break;
            case 4:
                drawStep4();
                break;
        }

        requestAnimationFrame(animateVisualizer);
    };
    animateVisualizer();
});
