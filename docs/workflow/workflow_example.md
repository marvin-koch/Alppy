# Alppy Teacher Workflows
## Typical Use Cases & Design Scenarios

**Document Purpose:** This document describes 10 realistic workflows that teachers will perform using Alppy. Each workflow includes step-by-step actions, specific details, and contextual information to support application design, testing, and validation.

**Target User:** Secondary school math teachers (grades 7-9, students aged 12-15)
**Application Context:** Temporal organization, adaptive worksheets, VLM auto-grading, ZPD-aligned exercise generation

---

## Workflow 1: Starting a New Teaching Unit

**Scenario:** Marie, a 9th-grade math teacher, is beginning a unit on quadratic equations that will run for 8 teaching periods (2 weeks). She needs to plan the unit structure and create the initial common exercises.

**Duration:** 30-45 minutes

### Step-by-Step Actions:

1. **Navigate to Dashboard**
   - Opens Alppy
   - Selects class "9A - Mathematics"
   - Views calendar/timeline showing current date and existing units

2. **Create New Unit/Theme**
   - Clicks "Create New Unit" button
   - Enters unit metadata:
     - Title: "Quadratic Equations"
     - Subject: "Algebra"
     - Duration: 8 periods
     - Start date: September 15
     - End date: September 29
     - Grade level: 9th grade
   - System displays visual confirmation on calendar

3. **Plan Unit Structure**
   - Application shows recommended structure for 8-period unit
   - Marie organizes into 3 phases:
     - Phase 1 (2 periods): Introduction & basic form
     - Phase 2 (3 periods): Solving methods
     - Phase 3 (3 periods): Applications & problem-solving
   - Saves phase structure; system logs timestamps

4. **Create Common Worksheet - Phase 1**
   - Clicks "Create Common Worksheet"
   - Selects "Phase 1: Introduction"
   - System auto-generates timestamp and versioning
   - Marie writes 8 problems covering:
     - Recognizing quadratic form
     - Identifying coefficients
     - Graphing basic parabolas
   - For each problem, she:
     - Types the problem statement
     - Adjusts answer box size using a slider (default: medium)
     - Specifies expected answer format (short form, numerical, etc.)
   - Reviews preview showing student-facing version
   - Publishes worksheet; system marks as "Common - Phase 1 - v1"

5. **Save & Schedule**
   - Sets worksheet as "active starting September 15"
   - Calendar updates showing worksheet availability
   - Creates notification for class that materials are ready

6. **Exit & Document**
   - System auto-saves all work
   - Timeline shows: "Unit created" → "Phase structure defined" → "Phase 1 common worksheet created"
   - Marie notes in unit journal: "8 intro problems ready, focus on form recognition"

**Key Application Features Used:**
- Calendar/temporal organization
- Unit templating and structure
- Answer box customization
- Versioning and timestamping
- Preview functionality
- Notifications

---

## Workflow 2: Distributing & Collecting Common Worksheets

**Scenario:** It's September 15. Marie distributes the first worksheet to her class of 24 students (9A). Students complete the worksheet on paper with printed QR codes and answer boxes. Marie scans submissions and uploads them to the system.

**Duration:** 5 minutes (distribution) + 20 minutes (collection/upload)

### Step-by-Step Actions:

1. **Print & Distribute**
   - Marie accesses "Phase 1 - Common Worksheet" in dashboard
   - Clicks "Print for class 9A"
   - System generates 24 copies with:
     - Unique QR code for each student (bottom left corner)
     - Corner registration markers (for later scanning)
     - Clear answer boxes below each problem
   - Marie prints on standard A4 paper
   - Distributes to class with instruction: "Complete all 8 problems. Write only in the answer boxes."

2. **Students Work (Not system action, but context)**
   - Students spend 45 minutes working on problems
   - Some write neatly in boxes; some write slightly outside (common for age 12-15)
   - Papers are filled with handwriting, cross-outs, scratch work

3. **Collect & Organize**
   - Marie collects 24 papers (one student absent)
   - In Alppy, clicks "Upload Submissions for Phase 1 Common Worksheet"
   - Selects "Batch upload via scanning"

4. **Scan Worksheets**
   - Marie uses document scanner or smartphone app to scan all 23 papers
   - System detects:
     - QR codes → automatically links to student identity
     - Corner registration markers → orients page correctly
     - Handwritten ink in answer boxes (template subtraction isolates writing)
   - Uploads PDF or image batch; system processes asynchronously

5. **System Processes & Stores**
   - VLM auto-grades all handwritten responses
   - Results appear in "Submissions" dashboard showing:
     - Student name | Problem 1 | Problem 2 | ... | Problem 8 | Score | Timestamp
   - Marie can review auto-graded results (with option to override if needed)
   - Missing student (absent) flagged for follow-up

6. **Review Initial Results**
   - Marie views "Class Overview" showing:
     - Average score: 72%
     - Students scoring >85%: 8 students
     - Students scoring 60-75%: 10 students
     - Students scoring <60%: 5 students
   - System notes: "Submission completed on Sept 15, 2:30 PM"

**Key Application Features Used:**
- Print-ready worksheet generation with QR codes
- Batch upload interface
- VLM auto-grading
- Score aggregation and segmentation
- Temporal logging (submission timestamps)
- Missing student tracking

---

## Workflow 3: Analyzing Results & Identifying Knowledge Gaps

**Scenario:** After collecting common worksheet data, Marie analyzes results to understand which concepts students struggled with and which students need support.

**Duration:** 20-30 minutes

### Step-by-Step Actions:

1. **View Submission Dashboard**
   - Opens "Phase 1 - Common Worksheet - Results"
   - System displays:
     - Overall class statistics (mean: 72%, median: 74%, std dev: 18%)
     - Item analysis (% correct per problem):
       - Problem 1 (Recognizing form): 87% ✓
       - Problem 2 (Coefficients): 65% ✗
       - Problem 3 (Coefficients): 62% ✗
       - Problem 4 (Graphing): 54% ✗
       - ...etc

2. **Identify Problem Areas**
   - Marie notices:
     - **Problem 2 & 3 cluster:** Only 65% and 62% solving coefficient identification
     - **Problem 4 cluster:** Only 54% solving graphing problems
   - Hypothesis: Students understand *form* but struggle with *manipulation*

3. **Student-Level Analysis**
   - Clicks on "Student Performance Breakdown"
   - Views student list sorted by score:
     - Top performers (>85%): Luc, Sophie, Thomas... (8 students)
     - Middle (60-85%): Marco, Lisa, Jean... (10 students)
     - Struggling (<60%): Alex, Nina, Romain... (5 students)
   - Clicks individual student (e.g., "Alex"):
     - Sees Alex's responses to each problem
     - Notes: Correct on 1, 2, 3 but blank or confused on 4-8
     - Hypothesis: Alex understands basics but gets overwhelmed by complexity

4. **Create Annotated Insights**
   - Marie writes in unit journal:
     - "Class struggling with graphing parabolas (Problem 4) - need more scaffolding"
     - "5 students need targeted intervention before Phase 2"
     - "Consider creating differentiated Phase 2 worksheets"
   - System timestamps this note: "Sept 15, 3:15 PM"

5. **Prepare for Differentiation**
   - Reviews ZPD alignment settings in application:
     - Default: "Adapt exercises based on student performance level"
     - Range: Same level | +1 level (harder) | -1 level (simpler)
   - Enables "Auto-generate personalized worksheets" for Phase 2
   - Sets parameters:
     - Number of groups: 3 (Struggling, Middle, Advanced)
     - Difficulty offset for advanced: +1 (more complex applications)
     - Difficulty offset for struggling: 0 (same level, more practice)

**Key Application Features Used:**
- Results dashboard with aggregated statistics
- Item analysis (per-problem performance)
- Student segmentation and sorting
- Individual student performance view
- Annotation/journaling with timestamps
- ZPD configuration interface
- Grouping/differentiation settings

---

## Workflow 4: Creating Differentiated Worksheets Based on Performance

**Scenario:** Based on Phase 1 results, Marie creates personalized worksheets for Phase 2. The system suggests exercises aligned to each student's ZPD, and Marie reviews and approves.

**Duration:** 40 minutes

### Step-by-Step Actions:

1. **Initiate Personalized Worksheet Generation**
   - Opens "Phase 2: Solving Methods"
   - Clicks "Generate Personalized Worksheets"
   - System displays:
     - "Create based on Phase 1 results? [YES]"
     - "Number of groups: 3"
     - "Learning objectives for Phase 2: [list]"

2. **System Generates Recommendations**
   - System organizes students into 3 groups:
     - **Group A (Struggling, 5 students):** Alex, Nina, Romain, etc.
     - **Group B (Middle, 10 students):** Marco, Lisa, Jean, etc.
     - **Group C (Advanced, 8 students):** Luc, Sophie, Thomas, etc.
   - For each group, system suggests:
     - Exercise difficulty level
     - Number of problems (suggested: 6-8)
     - Problem types and complexity
     - Estimated time to complete

3. **Review Group-Specific Recommendations**
   - Marie clicks on "Group A (Struggling)" to preview:
     - System suggests 6 problems with **reinforcement focus**:
       - 2 problems on coefficient identification (from Phase 1 gap)
       - 2 problems on graphing with scaffolding (step-by-step hints)
       - 2 problems mixing the two concepts
     - Difficulty level: "Same as Phase 1 average"
     - Note: "Group A students showed weakness in graphing; these problems include more structure"

   - Marie clicks on "Group C (Advanced)" to preview:
     - System suggests 8 problems with **extension focus**:
       - 3 problems on solving quadratics (new for Phase 2)
       - 2 problems with complex coefficients or irrational roots
       - 2 advanced application problems
       - 1 challenge problem (Completing the square variation)
     - Difficulty level: "+1 (more advanced)"
     - Note: "Group C students mastered form and graphing; ready for solving methods at higher complexity"

4. **Customize Each Worksheet**
   - **For Group A:**
     - Marie reviews the 6 suggested problems
     - Accepts first 4, replaces problem 5 with simpler variant
     - Adjusts answer box sizes: Medium (students need space for working)
     - Adds note: "Group A - Take your time, show all working"
   
   - **For Group B:**
     - Reviews standard 7 problems
     - Accepts all with minor adjustment to problem 6
     - Answer box sizes: Standard
     - Adds challenge note: "Group B - Try the challenge extension at the end"
   
   - **For Group C:**
     - Reviews 8 advanced problems
     - Accepts all; adds two optional challenge problems
     - Answer box sizes: Standard + larger for working
     - Adds note: "Group C - These problems require more thinking. Show your reasoning."

5. **Add Personalized Feedback Templates**
   - For each group, Marie adds feedback messages that will appear **after grading**:
     - **Group A:** "Great effort! You're making progress on graphing. Next, we'll practice more coordinate systems."
     - **Group B:** "Solid work! You're ready to move forward. Keep challenging yourself on the harder problems."
     - **Group C:** "Excellent mastery! You're ready for advanced solving techniques. Try the challenge problems for extra learning."

6. **Publish Personalized Worksheets**
   - Clicks "Publish Phase 2 Worksheets (Differentiated)"
   - System displays confirmation:
     - "Group A: 5 students, 6 problems, Reinforcement focus"
     - "Group B: 10 students, 7 problems, Standard progression"
     - "Group C: 8 students, 8 + 2 optional, Advanced focus"
   - Calendar updates; worksheets marked as "Active - Sept 22"
   - Students will receive their specific version based on group assignment

7. **Document the Decision**
   - Marie notes in unit journal:
     - "Phase 2 worksheets created with 3-group differentiation based on Phase 1 performance"
     - "Group A needs reinforcement on graphing; included scaffolded problems"
     - "Group C ready for advanced solving methods"
   - System logs: "Sept 16, 10:30 AM - Personalized worksheets generated and published"

**Key Application Features Used:**
- Automatic student grouping based on performance
- ZPD-aligned exercise recommendations
- Group-level worksheet customization
- Answer box size adjustment per group
- Personalized feedback template creation
- Multi-group publishing
- Temporal logging

---

## Workflow 5: Grading, Reviewing, & Providing Personalized Feedback

**Scenario:** One week later, Phase 2 worksheets have been completed and scanned. Marie reviews results, VLM auto-grades, and she provides personalized feedback for each student.

**Duration:** 45 minutes

### Step-by-Step Actions:

1. **Access Phase 2 Results**
   - Opens "Phase 2: Solving Methods - Results"
   - System shows submission status:
     - Group A (5 students): All submitted
     - Group B (10 students): 9 submitted, 1 absent (Lisa)
     - Group C (8 students): All submitted
   - Overall class performance: 78% (up from 72%)

2. **Review Auto-Grading Results**
   - VLM has automatically graded all 22 submissions
   - System displays:
     - Group A results (6 problems each):
       - Average: 71% (up from 50% on Phase 1)
       - Trend: **Positive improvement**
     - Group B results (7 problems each):
       - Average: 79%
       - Consistent with Phase 1 performance
     - Group C results (8 problems each):
       - Average: 86%
       - Mastery confirmed; ready for next level

3. **Review Item Analysis**
   - Problems with low performance (Group A focus):
     - Problem 2 (Graphing scaffolded): 40% — students still confused
     - Problem 5 (Mixed practice): 60% — partial understanding
   - Marie notes: "Graphing is still a significant barrier; may need more direct instruction"

4. **Provide Individualized Feedback**
   - Clicks on "Student Feedback" section
   - For each student, system shows:
     - Their worksheet (scanned image with graded answers)
     - Auto-generated score breakdown
     - Marie can add **personalized written feedback**
   
   - **Example: Alex (Group A, Score: 68%)**
     - System shows Alex's responses
     - Notes: Correct on reinforcement problems 1-3, struggled on problems 4-6
     - Marie writes personalized feedback:
       > "Alex, you did great on identifying coefficients (problems 1-3)! That's solid progress from Phase 1. For problems 4-6, I see you're still finding graphing tricky. Let's work together on this after class today. You're on the right track!"
     - Feedback tagged: "Encouragement + Targeted intervention needed"
   
   - **Example: Sophie (Group C, Score: 95%)**
     - Notes: Correct on all 8 problems, completed optional challenges
     - Marie writes:
       > "Sophie, this is excellent work! You've mastered solving methods at the standard level AND tackled the challenge problems. In Phase 3, I'll give you even more complex real-world applications to explore. Well done!"
     - Feedback tagged: "Mastery + Extension ready"

5. **Flag Students for Intervention**
   - System automatically highlights:
     - **Group A students with <65%:** Alex, Nina, Romain
     - Marie creates intervention note:
       - "These 3 students need additional graphing practice before Phase 3"
       - "Plan: Small group session on Sept 24, 30 minutes"
       - "Possible follow-up worksheet with extra scaffolding"

6. **Plan Next Steps**
   - Marie reviews "Phase 2 → Phase 3 Recommendations":
     - Group A: Optional mini-worksheet on graphing before Phase 3
     - Group B: Move forward to Phase 3 (standard difficulty)
     - Group C: Phase 3 with advanced applications + independent project option
   - Clicks "Approve Progression Plan"
   - System notes: "Sept 23, 2:00 PM - Phase 2 reviewed, progression approved"

**Key Application Features Used:**
- Submission tracking with status indicators
- Auto-grading review interface
- Item-level performance analysis
- Personalized feedback composition tool
- Feedback tagging and categorization
- Automatic intervention flagging
- Progression recommendations
- Temporal documentation

---

## Workflow 6: Managing Multiple Classes with Different Paces

**Scenario:** Marie teaches three 9th-grade classes (9A, 9B, 9C) with different paces. 9A is advanced and ahead; 9C is slower and needs more time. She needs to manage these three tracks simultaneously.

**Duration:** Ongoing management; 20 minutes per review cycle

### Step-by-Step Actions:

1. **Dashboard Overview**
   - Opens Alppy main dashboard
   - System shows timeline with three parallel class tracks:
     - **9A (Advanced):** Week 2 of Quadratic Equations, Phase 2 complete
     - **9B (Standard):** Week 1 of Quadratic Equations, working on Phase 1
     - **9C (Slower pace):** Still in unit introduction, Phase 1 starting this week
   - Color-coded indicators show each class's progress

2. **Check 9A Status (Advanced)**
   - Clicks "9A - Mathematics"
   - Sees Phase 2 complete; Phase 3 ready to start
   - Notes: This class averaged 82% on Phase 2 (high performance)
   - Marie decides to accelerate: "Can I start Phase 3 with added complexity?"
   - System recommends: "Phase 3 Advanced Track (9-10 problems, extensions available)"
   - Marie approves; Phase 3 worksheet published for 9A starting Sept 22

3. **Check 9B Status (Standard)**
   - Clicks "9B - Mathematics"
   - Sees Phase 1 in progress (submissions expected Sept 20)
   - Average predicted completion: Sept 20
   - Marie notes timeline: Phase 1 (Sept 15-20) → Phase 2 (Sept 22-28) → Phase 3 (Sept 29-Oct 5)
   - Worksheet already prepared for Phase 2 (standard track)

4. **Check 9C Status (Slower Pace)**
   - Clicks "9C - Mathematics"
   - Sees Phase 1 just starting (Sept 17)
   - System alerts: "Pacing 3 days behind planned schedule"
   - Marie reviews current plan:
     - Phase 1: Sept 17-22 (6 days instead of 4)
     - Phase 2: Sept 24-Oct 1 (4 days)
     - Phase 3: Oct 2-8 (2 days)
   - Decision: Phase 2 worksheet needs longer, simpler version
   - Marie modifies Phase 2 for 9C:
     - Reduces from 7 problems to 5 (focuses on core concepts)
     - Increases scaffolding/hints
     - Extends answer boxes (more space for working)

5. **Create Differentiated Phase 2 for 9C**
   - Uses template from standard Phase 2
   - Removes 2 complex problems
   - Adds 1 simplified problem with step-by-step guidance
   - System marks: "Phase 2 - 9C Adapted (5 problems, extended scaffolding)"
   - Schedules for Sept 24 (when Phase 1 is expected complete)

6. **Manage Timeline Visually**
   - Views "Multi-Class Timeline" showing all three 9th-grade classes:
     - **9A:** Phase 1 ✓ → Phase 2 ✓ → Phase 3 (Sept 22) [ADVANCED]
     - **9B:** Phase 1 (Sept 15-20) → Phase 2 (Sept 22-28) → Phase 3 (Sept 29) [STANDARD]
     - **9C:** Phase 1 (Sept 17-22) → Phase 2 (Sept 24-Oct 1) → Phase 3 (Oct 2-8) [EXTENDED]
   - System highlights key dates and differentiations

7. **Document Multi-Class Management**
   - Marie's master journal entry:
     - "Three-track management setup: 9A advanced, 9B standard, 9C extended"
     - "9A Phase 3 accelerated (Sept 22)"
     - "9C Phase 2 simplified (5 problems, more scaffolding)"
     - "Next review: Sept 20 (when 9B Phase 1 completes)"

**Key Application Features Used:**
- Multi-class dashboard overview
- Parallel timeline visualization
- Class-level pacing alerts
- Differentiated worksheet versioning per class
- Timeline management and adjustment
- Advanced/Standard/Extended track templates

---

## Workflow 7: Preparing for Parent-Teacher Conference

**Scenario:** Parent-teacher conferences are next week. Marie needs to prepare data and insights for three parent meetings: one for an advanced student, one for an average student, and one for a struggling student.

**Duration:** 30 minutes

### Step-by-Step Actions:

1. **Export Class Performance Summary**
   - Opens "Reports" section
   - Clicks "Generate Parent Conference Report"
   - System prompts: "Select class (9A, 9B, 9C)" → Marie selects 9B
   - Report options: Summarize by unit, phase, or full term
   - Marie selects: "Quadratic Equations Unit (Phases 1-2)"

2. **Generate Individual Student Reports**
   - Marie selects three students for conferences:
     - **Luc (Advanced):** 88% average
     - **Marco (Average):** 74% average
     - **Alex (Struggling):** 65% average

   - For **Luc (Advanced):**
     - System generates report showing:
       - Phase 1 score: 92%
       - Phase 2 score: 95%
       - Strength: Mastery of graphing (100% on graphing problems)
       - Areas explored: Advanced extensions, challenge problems
       - Recommendation: "Ready for advanced coursework; consider gifted program"
     - Marie adds note: "Talk to Luc about independent project for Phase 3"

   - For **Marco (Average):**
     - System generates report:
       - Phase 1 score: 75%
       - Phase 2 score: 72%
       - Strengths: Consistent, shows understanding of core concepts
       - Areas for growth: Complexity increases drop performance slightly
       - Recommendation: "Solid progress; encourage consistent effort"
     - Marie adds note: "Marco is reliable; encourage him to attempt challenge problems"

   - For **Alex (Struggling):**
     - System generates report:
       - Phase 1 score: 52%
       - Phase 2 score: 68%
       - Strength: **Clear improvement trend** (16% gain from Phase 1 to 2)
       - Challenge: Graphing still a barrier; needs additional practice
       - Intervention: Received targeted small-group sessions
       - Recommendation: "Alex is making progress; continue support, consider tutoring"
     - Marie adds detailed note:
       > "Alex has made real progress with our intervention. He went from 52% to 68% by focusing on reinforcement practice. His graphing skills are improving. I'd recommend continued small-group work and possibly a peer mentor next unit."

3. **Create Personalized Talking Points**
   - For each student, Marie creates bullet-point talking points:
   
   - **Luc's parents:**
     - "Mastered all Phase 1 & 2 concepts"
     - "Scored 95% on Phase 2 — among top in class"
     - "Successfully tackled advanced challenge problems"
     - "Recommendation: Advanced independent project or gifted math program"
   
   - **Marco's parents:**
     - "Consistent B-level performance (72-75%)"
     - "Understands core material well"
     - "When difficulty increases, performance dips slightly — this is normal"
     - "Encourage: Attempt challenge problems for confidence building"
   
   - **Alex's parents:**
     - "Started Phase 1 with difficulty (52%)"
     - "Has made significant progress through Phase 2 (68% — 16% improvement!)"
     - "Specific strength: Now understands coefficients and basic form"
     - "Challenge area: Graphing (working on this with extra practice)"
     - "Plan: Continue targeted practice, possibly peer mentor"

4. **Generate Visual Performance Charts**
   - System creates comparison chart showing:
     - Individual score progression (Phase 1 → Phase 2)
     - Class average trend line
     - Individual placement relative to class
   - Marie can export as PDF or view during conference

5. **Save Conference Materials**
   - Marie exports all three student reports to PDF
   - Saves to conference folder: "9B_ParentConferences_Sept"
   - System timestamps: "Sept 19, 10:00 AM - Conference materials generated"
   - Prints reports for use during conferences

**Key Application Features Used:**
- Class performance summary generation
- Individual student report cards with progression
- Strength/challenge identification
- Trend analysis (improvement over time)
- Intervention documentation
- Recommendation generation
- PDF export for sharing
- Visual progress charts

---

## Workflow 8: Re-Teaching a Concept Using Diagnostic Data

**Scenario:** After reviewing Phase 2 results, Marie noticed that 30% of the class still struggles with graphing parabolas. Rather than moving forward, she decides to re-teach this concept using a mini-diagnostic-worksheet cycle.

**Duration:** 60 minutes (planning) + classroom time (teaching)

### Step-by-Step Actions:

1. **Identify the Teaching Gap**
   - Reviews Phase 2 results again:
     - Problem 4 (Graphing): 54% correct
     - Problem 7 (Graphing application): 48% correct
   - System suggests: "Multiple students showing weakness in graphing; consider diagnostic and re-teach"
   - Marie clicks "Recommend Re-teaching Cycle"

2. **Create Diagnostic Mini-Worksheet**
   - Clicks "Create Diagnostic Worksheet"
   - System prompts: "What skill? Graphing parabolas"
   - Marie configures:
     - Duration: 15 minutes (quick diagnostic)
     - Problems: 4 problems (simple to complex):
       - Plot point on coordinate system
       - Identify vertex from graph
       - Sketch parabola from coefficients
       - Identify properties from graph
     - Answer box sizes: Standard (quick working)
   - Publishes as "Diagnostic: Graphing Parabolas (Pre-Reteach)"

3. **Administer & Collect Diagnostic**
   - Next class period, Marie distributes diagnostic worksheet
   - Students complete in 15 minutes
   - Marie scans submissions; VLM auto-grades within minutes
   - Results show:
     - 8 students: 100% (don't need reteach)
     - 10 students: 50-75% (confused on vertices/properties)
     - 5 students: 0-25% (fundamental misunderstanding)

4. **Plan Targeted Re-Teaching**
   - System suggests grouping:
     - **Group A (8 students, 100%):** Advance to Phase 3 while reteach happens
     - **Group B (10 students, 50-75%):** Small group reteach session (30 min)
     - **Group C (5 students, 0-25%):** One-on-one intensive support
   - Marie schedules:
     - Group B: Reteach session Sept 26, 1:30 PM (during office hours)
     - Group C: Individual sessions Sept 26-27

5. **Prepare Re-Teaching Materials**
   - Clicks "Generate Re-Teaching Worksheet"
   - System suggests scaffolded approach:
     - Problem 1: Vertex identification (with scaffolding)
     - Problem 2: Property reading from graph (step-by-step)
     - Problem 3: Sketching with provided vertex/axis
     - Problem 4: Independent graphing
   - Marie reviews and accepts with minor modifications
   - Marks as "Reteach: Graphing (Scaffolded) - Sept 26"

6. **Teach the Lesson**
   - During reteach session, Marie:
     - Uses mini-whiteboard to demonstrate vertex identification
     - Works through Problem 1 with students
     - Guides students through Problem 2 together
     - Watches as Group B completes Problems 3-4 independently
     - Provides real-time feedback

7. **Administer Post-Reteach Assessment**
   - After reteach session, Marie distributes post-reteach worksheet
   - Same 4 problems, slightly different numbers
   - Scans and auto-grades; results appear in system:
     - Average improvement: From 65% → 82% ✓
     - System notes: "Reteach effective; 9 of 10 students now >75%"
     - 1 student (Nina) still at 60% → flagged for individual support

8. **Document Reteach Cycle**
   - Marie's unit journal:
     - "Diagnostic identified graphing weakness (54% on Phase 2 Problem 4)"
     - "Administered diagnostic worksheet: 10 students needed support"
     - "Conducted reteach session Sept 26: Average improvement 65% → 82%"
     - "Nina needs continued individual support on vertices"
     - "Group A (8 students) moved to Phase 3 during reteach"

9. **Adjust Progression Plan**
   - System updates class progression:
     - Groups B & C (15 students): Resume Phase 3 (Sept 27)
     - Group A (8 students): Already in Phase 3 (continue)
     - Nina: Pair with peer mentor for Phase 3, additional office hours
   - Calendar updated with new dates

**Key Application Features Used:**
- Diagnostic worksheet creation
- Quick-turnaround auto-grading
- Performance-based grouping for re-teaching
- Scaffolded worksheet generation
- Pre/post assessment comparison
- Progress documentation
- Adaptive progression planning

---

## Workflow 9: Monitoring Progress Across Multiple Students Over Time

**Scenario:** It's the end of the unit (Sept 29). Marie wants to see the overall learning progression for all students across all three phases to assess unit success and inform grading.

**Duration:** 25 minutes

### Step-by-Step Actions:

1. **Access Unit Analytics Dashboard**
   - Clicks "Analytics" → "Unit: Quadratic Equations"
   - System displays comprehensive overview:
     - Unit dates: Sept 15 - Sept 29
     - Class size: 24 students
     - Completion rate: 95% (23/24 submitted all phases)

2. **View Class Progression Across Phases**
   - System shows timeline chart:
     ```
     Phase 1 (Sept 15-20):  Avg 72% | Range 45%-98%
     Phase 2 (Sept 22-28):  Avg 78% | Range 52%-95%
     Phase 3 (Sept 29):     Avg 81% | Range 60%-98%
     ```
   - Trend: **Consistent improvement** across unit (+9% from Phase 1 to Phase 3)
   - System concludes: "Unit shows positive learning trend"

3. **Identify Learner Profiles**
   - System categorizes 23 students:
     - **High performers (>85% Phase 3):** 8 students
       - Consistent high achievement
       - Successfully tackled advanced extensions
     - **Steady improvers (Phase 1 < Phase 3, +10% or more):** 7 students
       - Clear growth trajectory
       - Examples: Alex (+16%), Romain (+12%), Jean (+14%)
     - **Consistent mid-range (70-80% across phases):** 6 students
       - Stable understanding
       - May need advanced strategies to accelerate
     - **Struggling throughout (<65% Phase 3):** 2 students
       - Nina (60%), Pierre (62%)
       - Need individual intervention planning

4. **Analyze Knowledge Domains**
   - System breaks down by concept:
     - **Form Recognition:** 87% mastery (strong across all phases)
     - **Coefficients:** 76% mastery (improved from Phase 1: 65% → Phase 3: 82%)
     - **Graphing:** 71% mastery (still challenging; improved from Phase 1: 54% → Phase 3: 78%)
     - **Solving Methods:** 83% mastery (solid progression Phase 2 → Phase 3)
     - **Applications:** 79% mastery (good but variable)
   - System notes: "Graphing remains the most challenging skill; recommend continued reinforcement"

5. **Export Student Mastery Levels**
   - System generates mastery summary showing each student:
     - Phase 1 → Phase 2 → Phase 3 scores
     - Trend (↑ improving, → stable, ↓ declining)
     - Concept strengths and weaknesses
   - Example for Alex:
     ```
     Alex - Growth Trajectory
     Phase 1: 52% ↑
     Phase 2: 68% ↑
     Phase 3: 69%
     Trend: Strong improvement then plateau
     Strengths: Form, coefficients, solving
     Challenge: Graphing (68% vs class average 78%)
     Recommendation: Continue graphing support
     ```

6. **Plan Individual Support Paths**
   - For high performers (8 students):
     - Recommend: Advanced unit next, independent projects, peer tutoring roles
   - For steady improvers (7 students):
     - Recommend: Positive reinforcement, continued scaffolding, challenge problems
   - For consistent mid-range (6 students):
     - Recommend: Targeted skill reinforcement, mixed difficulty practice
   - For struggling (2 students):
     - Recommend: Individual tutoring, simplified next-unit entry, parent communication

7. **Generate Unit Report**
   - Clicks "Generate Unit Summary Report"
   - System creates PDF including:
     - Unit overview (dates, objectives)
     - Class performance summary (graphs and statistics)
     - Individual student progress (mastery levels, trends)
     - Concept-level analysis (what the class mastered/struggled with)
     - Recommendations for next unit
   - Marie exports to "Reports/Unit_QuadraticEquations_Summary.pdf"

8. **Reflect in Unit Journal**
   - Marie's final entry:
     ```
     Unit: Quadratic Equations (Sept 15-29)
     Outcome: Successful unit with positive learning trend
     - Class average improved 9% across unit (72% → 81%)
     - 7 students showed strong growth (>10% improvement)
     - 8 students demonstrated mastery (>85%)
     - Challenge: Graphing remained difficult; consider front-loading graphing skills in next unit
     - Success: Differentiation strategy effective; all three class tracks completed unit
     Next steps: 2 students (Nina, Pierre) need intensive support for next unit
     ```

9. **Archive Unit Materials**
   - System archives all worksheets, results, and timelines
   - Accessible for future reference and analysis
   - Marked with unit completion date: Sept 29, 2024

**Key Application Features Used:**
- Comprehensive unit analytics dashboard
- Multi-phase progression visualization
- Learner profile categorization
- Concept-level mastery analysis
- Individual student mastery reports
- Trend identification (improvement/plateau/decline)
- Support recommendation engine
- PDF unit summary export
- Historical archiving

---

## Workflow 10: Planning Next Unit Using Previous Unit Data

**Scenario:** Based on the Quadratic Equations unit completion and analysis, Marie plans the next unit (Systems of Equations) for class 9B. She uses insights from the previous unit to shape the new unit structure and initial materials.

**Duration:** 40 minutes

### Step-by-Step Actions:

1. **Review Previous Unit Recommendations**
   - Opens "Quadratic Equations - Final Report"
   - Reads system recommendations:
     - "Graphing was challenging; consider prerequisite review in next unit"
     - "Students showing growth with differentiated approach; continue strategy"
     - "High performers ready for accelerated content"
     - "2 students need pre-unit intervention"

2. **Access Next Unit Template**
   - Clicks "Create Next Unit"
   - System suggests: "Based on curriculum progression, consider: Systems of Equations"
   - Marie confirms and selects unit template

3. **Set Unit Parameters Using Previous Data**
   - Unit name: "Systems of Equations"
   - Duration: 8 periods (based on similar complexity to Quadratic Equations)
   - Class: 9B
   - Integration of previous learning:
     - System prompts: "Include graphing prerequisite review?" 
     - Marie clicks YES (because graphing was 71% mastery)
     - System generates: Phase 0 (Mini-review: Graphing - 2 period focus)

4. **Build Unit Structure**
   - Marie organizes 8-period unit into phases:
     - **Phase 0 (New):** Graphing Review (prerequisite support) - 1 period
     - **Phase 1:** Introduction to systems - 2 periods
     - **Phase 2:** Solving methods - 3 periods
     - **Phase 3:** Applications - 2 periods

5. **Prepare Pre-Unit Support Materials**
   - System recommends grouping based on previous unit:
     - Group A (Nina, Pierre - previously struggling): **Require** graphing review before Phase 1
     - Group B (6 consistent mid-range): **Recommended** graphing review
     - Group C (8 high performers): **Optional** graphing review or skip to Phase 1
   - Marie creates:
     - **Required pathway:** Phase 0 (mandatory review) → Phase 1
     - **Recommended pathway:** Phase 0 (optional) → Phase 1
     - **Advanced pathway:** Phase 1 (skip Phase 0) + Phase 3 extensions

6. **Design Phase 0 Graphing Review**
   - Creates mini-worksheet: "Prerequisite Review: Graphing Review"
   - Problems focus on:
     - Plotting points quickly
     - Reading coordinates from graphs
     - Basic linear graphing (simple, not overwhelming)
   - Answer boxes: **Large** (students need comfort and space)
   - Tone: Encouraging ("Quick practice to refresh your skills!")
   - Difficulty: **Below Phase 1 level** (rebuild confidence)

7. **Plan Differentiation Strategy**
   - System suggests (based on previous unit's success):
     - "Use 3-group differentiation again? [YES]"
     - Marie configures:
       - Support: Nina, Pierre, + 4 mid-range students needing extra help
       - Standard: 6 consistent mid-range students
       - Advanced: 8 high performers
   - Pre-assigns students to projected groups
   - Notes: "Assignments flexible based on Phase 0 results"

8. **Create Initial Phase 1 Worksheet**
   - Begins "Phase 1: Introduction to Systems"
   - Starts with 6 problems on:
     - Recognizing systems (linear equations in two variables)
     - Graphing lines (single and pairs)
     - Identifying solutions graphically
   - For advanced students, adds challenge: "Find intersection algebraically"

9. **Set Expectations Based on Previous Unit**
   - Reflects on previous learnings:
     - "Differentiation effective; use again"
     - "Early diagnostic important; plan Phase 0 diagnostic"
     - "Reteaching worked well; be ready to offer graphing reteach if Phase 0 results weak"
     - "Student improvement is real; Alex's growth shows progress is possible"
   - Notes in unit setup:
     ```
     Unit: Systems of Equations (Oct 1-17)
     Previous unit insights:
     - Graphing was challenging → added Phase 0 review
     - Differentiation effective → 3-group model
     - Early support helps late bloomers → Nina & Pierre in support track
     - High performers accelerate well → Advanced pathway available
     ```

10. **Prepare First Class Materials**
    - Generates Phase 0 diagnostic worksheet
    - Schedules for Oct 1
    - Plans short introduction: "Today we're warming up with graphing skills"
    - Prepares to collect and auto-grade Phase 0 on day 1
    - System calendar updates showing new unit structure

11. **Save & Archive**
    - System saves unit structure
    - Links to previous unit: "Quadratic Equations (Sept) → Systems of Equations (Oct)"
    - Timestamps: "Sept 29, 3:30 PM - Systems of Equations unit structure created"
    - Previous unit now archived; new unit ready for launch Oct 1

**Key Application Features Used:**
- Previous unit analysis integration
- System recommendations based on data
- Unit template with prerequisite customization
- Learner-path customization (Required / Recommended / Advanced)
- Support grouping pre-assignment based on previous performance
- Confidence-building worksheet design
- Unit linking and progression tracking
- Launch scheduling

---

## Summary

These 10 workflows demonstrate how teachers use Alppy across the full cycle of:
1. **Planning** (Workflow 1, 10)
2. **Delivering** (Workflow 2, 6)
3. **Assessing** (Workflow 3, 5, 8)
4. **Differentiating** (Workflow 4, 6, 7)
5. **Reflecting** (Workflow 9)
6. **Iterating** (Workflow 8, 10)

Each workflow showcases key features:
- Temporal organization (calendar, timelines, sequencing)
- Data-driven differentiation (ZPD alignment, grouping)
- Automated grading (VLM, handwriting recognition)
- Personalized feedback and support
- Multi-class management
- Progress tracking and analytics

**Next Steps:**
- Review format and content with stakeholders
- Validate with actual teacher feedback
- Expand to additional workflows (e.g., homework management, parent notifications, assessment planning)
- Use as design validation scenarios for product testing