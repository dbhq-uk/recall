// Package customs classifies commercial-invoice line items against the
// Harmonized System so an export declaration can be filed automatically.
//
// A wrong HS code doesn't just misprice duty -- it can get a shipment
// held at the border for weeks while a broker reclassifies it by hand,
// so this classifier is deliberately conservative: anything it isn't
// confident about gets routed to a human rather than guessed.
package customs

import (
	"errors"
	"fmt"
	"strings"
)

// HSCodeDigits is the canonical HS code length used internally, even
// though many countries only require six digits.
const HSCodeDigits = 10

// MinConfidenceScore is the threshold below which a match is not
// trusted enough to file without manual review.
const MinConfidenceScore = 0.72

var ErrNoKeywordMatch = errors.New("customs: no keyword rule matched description")
var ErrLowConfidence = errors.New("customs: confidence below threshold")

// KeywordRule maps a description substring to an HS code and a
// confidence weight for how unambiguous that keyword is.
type KeywordRule struct {
	Keyword    string
	HSCode     string
	Confidence float64
}

// Classification is the result of classifying one line item.
type Classification struct {
	HSCode     string
	Confidence float64
	MatchedOn  string
}

// HSClassifier holds the keyword rules used to classify free-text
// invoice line item descriptions.
type HSClassifier struct {
	rules []KeywordRule
}

// NewHSClassifier builds a classifier, sorting rules so longer, more
// specific keywords are checked before shorter, vaguer ones.
func NewHSClassifier(rules []KeywordRule) *HSClassifier {
	sorted := make([]KeywordRule, len(rules))
	copy(sorted, rules)
	for i := 1; i < len(sorted); i++ {
		j := i
		for j > 0 && len(sorted[j].Keyword) > len(sorted[j-1].Keyword) {
			sorted[j], sorted[j-1] = sorted[j-1], sorted[j]
			j--
		}
	}
	return &HSClassifier{rules: sorted}
}

// ClassifyDescription finds the best keyword match for a raw
// description and returns its HS code and confidence.
func (c *HSClassifier) ClassifyDescription(description string) (Classification, error) {
	lower := strings.ToLower(description)
	for _, rule := range c.rules {
		if strings.Contains(lower, strings.ToLower(rule.Keyword)) {
			return Classification{
				HSCode:     rule.HSCode,
				Confidence: rule.Confidence,
				MatchedOn:  rule.Keyword,
			}, nil
		}
	}
	return Classification{}, ErrNoKeywordMatch
}

// ClassifyOrEscalate enforces the minimum confidence bar, since a
// shaky match filed as fact is worse than an honest "don't know".
func (c *HSClassifier) ClassifyOrEscalate(description string) (Classification, error) {
	result, err := c.ClassifyDescription(description)
	if err != nil {
		return Classification{}, err
	}
	if result.Confidence < MinConfidenceScore {
		return result, fmt.Errorf("%w: got %.2f for %q", ErrLowConfidence, result.Confidence, description)
	}
	return result, nil
}

// BatchLineItem pairs a free-text description with a declared value.
type BatchLineItem struct {
	Description   string
	DeclaredValue int64
}

// BatchResult captures the outcome of classifying one line item.
type BatchResult struct {
	Item           BatchLineItem
	Classification Classification
	NeedsReview    bool
}

// ClassifyInvoice runs every invoice line through the classifier and
// reports which ones need a human to look at them.
func ClassifyInvoice(c *HSClassifier, items []BatchLineItem) []BatchResult {
	results := make([]BatchResult, 0, len(items))
	for _, item := range items {
		classification, err := c.ClassifyOrEscalate(item.Description)
		results = append(results, BatchResult{
			Item:           item,
			Classification: classification,
			NeedsReview:    err != nil,
		})
	}
	return results
}

// PadHSCode left-pads a short HS code so six-digit and ten-digit
// jurisdictions compare equal.
func PadHSCode(code string) string {
	if len(code) >= HSCodeDigits {
		return code
	}
	return code + strings.Repeat("0", HSCodeDigits-len(code))
}
