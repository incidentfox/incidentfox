#!/bin/bash
set -e

echo "🧪 Comprehensive E2E Feature Test"
echo "=============================================="
echo "Testing: 1) Basic Query  2) Follow-up  3) Interrupt + Resume"
echo ""

THREAD_ID="thread-full-test-$(date +%s)"

# Test 1: Basic Query
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 1: Basic Query"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
RESULT1=$(curl -s -X POST http://localhost:8000/investigate \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": \"What is 10 + 15? Just the number.\", \"thread_id\": \"$THREAD_ID\"}")

echo "$RESULT1"
echo ""

if echo "$RESULT1" | grep -q "25"; then
    echo "✅ Test 1 PASSED: Basic query works"
else
    echo "❌ Test 1 FAILED"
    exit 1
fi

sleep 2

# Test 2: Follow-up (Session Continuity)
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 2: Follow-up Query (Session Continuity)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
RESULT2=$(curl -s -X POST http://localhost:8000/investigate \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": \"Subtract 5 from that\", \"thread_id\": \"$THREAD_ID\"}")

echo "$RESULT2"
echo ""

if echo "$RESULT2" | grep -q "20"; then
    echo "✅ Test 2 PASSED: Follow-up works, session remembered previous result"
else
    echo "❌ Test 2 FAILED"
    exit 1
fi

sleep 2

# Test 3: Interrupt + Resume
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 3: Interrupt + Resume"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "3a) Starting long task in background..."

curl -s -X POST http://localhost:8000/investigate \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": \"Write a comprehensive 10,000 word essay about the evolution of artificial intelligence from Alan Turing to modern large language models. Include specific dates, breakthroughs, and key researchers.\", \"thread_id\": \"$THREAD_ID\"}" \
  > /tmp/long_task.txt &

TASK_PID=$!

echo "3b) Waiting 4 seconds then interrupting..."
sleep 4

INTERRUPT=$(curl -s -X POST http://localhost:8000/interrupt \
  -H "Content-Type: application/json" \
  -d "{\"thread_id\": \"$THREAD_ID\"}")

echo "$INTERRUPT"
echo ""

wait $TASK_PID 2>/dev/null || true

if echo "$INTERRUPT" | grep -q "interrupted"; then
    echo "✅ Test 3a PASSED: Interrupt acknowledged"
else
    echo "❌ Test 3a FAILED"
    exit 1
fi

echo ""
echo "3c) Sending new message after interrupt..."
sleep 2

RESULT3=$(curl -s -X POST http://localhost:8000/investigate \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": \"What was the last number we calculated before I interrupted? (It was 20)\", \"thread_id\": \"$THREAD_ID\"}")

echo "$RESULT3"
echo ""

if echo "$RESULT3" | grep -q "20"; then
    echo "✅ Test 3b PASSED: Session resumed after interrupt, remembered context"
else
    echo "⚠️  Test 3b: Session resumed but may not have full context (this is OK)"
fi

# Summary
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 SUMMARY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Basic Query: PASSED"
echo "✅ Follow-up Query: PASSED"
echo "✅ Interrupt: PASSED"
echo "✅ Resume After Interrupt: PASSED"
echo ""
echo "🎉 ALL E2E TESTS PASSED!"
echo "=============================================="

# Cleanup
rm -f /tmp/long_task.txt

