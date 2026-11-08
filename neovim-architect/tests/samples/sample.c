#include <stdio.h>
int main(void) {
    int x = "not an int"; /* intentional error */
    printf("%d\n", x);
    return 0;
}
